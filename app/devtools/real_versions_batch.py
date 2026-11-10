# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""真机验收：多版本与批量复用的“写入 + 撤销”（1.1.0）。只给维护者用，不属于 pytest，也不会被打进安装包。

用法（在仓库根目录）：
    <conda lrmcp 环境的 python> app/devtools/real_versions_batch.py

安全前提（任何一条不满足，脚本立即退出，不做任何修改）：
  1. Lightroom 已打开，并且打开的是**测试目录**：目录文件的路径里必须含 "ceshi"。脚本先问插件要 catalog_path，
     不含 "ceshi" 就退出。绝不要对真实照片目录运行。
  2. LrMCP 插件已启用；只读开关（~/LrMcp/readonly、环境变量 LRMCP_READONLY=1）没有打开。
  3. 在 Lightroom 里选中 2 到 10 张照片（批量上限 10 张）。运行期间不要改选区、不要手动调照片。
  4. 建议先关掉 Latos Hue 和其他 AI 会话：插件同时轮询的服务越少，结果越稳定。

脚本做什么（每一步打印 PASS / FAIL 和耗时）：
  读初始参数快照 → 保存版本 A → 小改动（曝光 +0.10，曝光已接近上限时改为 -0.10）→ 保存版本 B
  → 应用版本 A 并核对回到 A → 撤销这次应用并核对回到 B
  → 用那次小改动生成批量预演、应用到其余选中照片、逐张核对变化、整批还原并核对
  → 收尾：把所有照片恢复到初始快照并逐项核对，删除本次创建的两个版本。
任何一步失败或抛异常，都会走同一个收尾（恢复到初始快照 + 删除测试版本）。

走哪条路径：所有**写入、撤销、版本、批量**都只调用 server 的 EditService 公开方法
（set_develop / save_version / apply_version / restore / batch_plan_from_edit / batch_apply / restore_original /
delete_version），与软件界面走的是同一条路径（app/lr_service.py 也是调它们）。脚本自己不拼任何写入类的插件命令；
只用了三个只读命令来核对结果：status（取目录路径）、list_selected（取选中照片）、snapshot（读参数）。

修改记录放在临时文件夹（不混进 ~/LrMcp/edits 里你平时的记录）；版本用软件同一个版本库，名字带随机后缀，结束时删除。
退出码：0 全部通过；1 有 FAIL；2 前提不满足（没有做任何修改）。
"""
from __future__ import annotations

import secrets
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from lightroom_mcp.bridge import Bridge, BridgeBusy  # noqa: E402
from lightroom_mcp.edits import VOLATILE_PRESET_KEYS, EditService, EditStore  # noqa: E402

CATALOG_MARK = "ceshi"
STEP = 0.10                     # 小改动：曝光 +0.10
CONNECT_WAIT = 40
failures = 0


def check(label: str, ok: bool, t0: float, detail: str = "") -> bool:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}  [{time.monotonic() - t0:.1f}s]{(' — ' + detail) if detail else ''}", flush=True)
    return bool(ok)


def close(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-3
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return a == b


def differences(expected: dict, now: dict) -> list[str]:
    """expected 里有、而现在不一样的参数名（开始时不存在的键是 Lightroom 的内部值，不计）。
    LensBlur（镜头模糊）不计：Lightroom 渲染预览时会自己改写它的数值（深度图的焦点范围等），与我们的写入无关，
    服务端对预设同样把它当作"易变键"（VOLATILE_PRESET_KEYS）。真机教训：1.1.0 首次验收时它在没有被我们写入的照片上"变了"。"""
    return sorted(k for k in expected if k not in VOLATILE_PRESET_KEYS and not close(expected.get(k), now.get(k)))


def main() -> int:
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(f"REFUSED: 无法启动连接服务：{e}")
        return 2

    def snapshot(photo_id: str) -> dict:
        return bridge.call("snapshot", {"photo": photo_id}, timeout=60)["settings"]

    store_dir = Path(tempfile.mkdtemp(prefix="latoshue-accept-"))
    service = EditService(bridge.call, EditStore(store_dir))      # 只读开关、版本库用默认的（与软件相同）
    suffix = secrets.token_hex(3)
    name_a, name_b = f"验收A-{suffix}", f"验收B-{suffix}"
    starts: dict[str, dict] = {}
    names: dict[str, str] = {}
    active = ""
    made_versions: list[str] = []
    edits: list[str] = []          # 本脚本在活动照片上做的单张修改，按先后
    batch_id = ""
    try:
        # ---- 前提检查：这一段不做任何修改 ----
        if not bridge.wait_connected(CONNECT_WAIT):
            print(f"REFUSED: 插件在 {CONNECT_WAIT} 秒内没有连上。请确认 Lightroom 已打开、LrMCP 插件已启用。")
            return 2
        status = bridge.call("status")
        catalog = str(status.get("catalog_path") or "")
        if CATALOG_MARK not in catalog.lower():           # 断言：只在测试目录上运行
            print(f"REFUSED: 当前不是测试目录（路径里没有 \"{CATALOG_MARK}\"）：{catalog or '读不到目录路径'}")
            return 2
        print(f"测试目录：{catalog}")
        try:
            service.check_writable()
        except Exception as e:  # noqa: BLE001
            print(f"REFUSED: {e}")
            return 2
        listing = bridge.call("list_selected", {"limit": 11}, timeout=30)
        count, photos = listing.get("count", 0), listing.get("photos") or []
        if not 2 <= count <= 10 or len(photos) != count:
            print(f"REFUSED: 请在 Lightroom 里选中 2 到 10 张照片（现在选中 {count} 张）。")
            return 2
        active = listing.get("active_id") or photos[0]["id"]
        names = {p["id"]: p.get("name") or p["id"][:8] for p in photos}
        others = [pid for pid in names if pid != active]
        print("选中的照片：" + "、".join(f"{names[i]}{'（当前）' if i == active else ''}" for i in names) + "\n")

        # ---- 1. 初始快照 ----
        t0 = time.monotonic()
        for pid in names:
            starts[pid] = snapshot(pid)
        check(f"读初始参数快照（{len(starts)} 张）", all(isinstance(s, dict) and "Exposure2012" in s for s in starts.values()), t0)

        # ---- 2. 保存版本 A ----
        t0 = time.monotonic()
        saved = service.save_version(name_a, "真机验收用，结束时删除", active)
        made_versions.append(name_a)
        listed = [v["name"] for v in service.list_versions(active)["versions"]]
        check(f"保存版本 A（{name_a}）", saved.get("version") == name_a and name_a in listed, t0,
              f"存了 {saved.get('saved_settings')} 项参数")
        check("保存版本不改照片", not differences(starts[active], snapshot(active)), t0)

        # ---- 3. 小改动：曝光 ±0.10 ----
        t0 = time.monotonic()
        exp0 = float(starts[active]["Exposure2012"])
        delta = STEP if exp0 + STEP <= 4.9 else -STEP
        done = service.set_develop({"Exposure2012": round(exp0 + delta, 4)}, reason="真机验收：小改动", photo=active)
        edits.append(done["edit_id"])
        state_b = snapshot(active)
        check(f"小改动：曝光 {exp0:+.2f} → {exp0 + delta:+.2f}", bool(done.get("verified")) and close(state_b["Exposure2012"], exp0 + delta), t0,
              f"edit_id={done['edit_id']}")

        # ---- 4. 保存版本 B ----
        t0 = time.monotonic()
        saved = service.save_version(name_b, "真机验收用，结束时删除", active)
        made_versions.append(name_b)
        check(f"保存版本 B（{name_b}）", saved.get("version") == name_b, t0)

        # ---- 5. 应用版本 A，核对回到 A ----
        t0 = time.monotonic()
        applied = service.apply_version(name_a, reason="真机验收：应用版本 A", photo=active)
        apply_id = applied.get("edit_id") or ""
        if apply_id:
            edits.append(apply_id)
        diff = differences(starts[active], snapshot(active))
        check("应用版本 A：参数回到 A（= 初始快照）", bool(apply_id) and bool(applied.get("verified")) and not diff, t0,
              f"改了 {applied.get('settings_changed')} 项" + (f"；不一致：{diff[:8]}" if diff else ""))

        # ---- 6. 撤销这次应用，核对回到 B ----
        t0 = time.monotonic()
        undone = service.restore(apply_id) if apply_id else {}
        diff = differences(state_b, snapshot(active))
        ok = check("撤销应用：参数回到 B", bool(undone.get("verified")) and not diff, t0, f"不一致：{diff[:8]}" if diff else "")
        if ok and apply_id:
            edits.remove(apply_id)

        # ---- 7. 批量复用：预演 → 应用 → 核对 → 整批还原 ----
        t0 = time.monotonic()
        plan = service.batch_plan_from_edit(edits[0], "selected", reason="真机验收：批量复用")
        planned = {r["photo_id"]: r for r in plan.get("photos", [])}
        check("批量预演：不含来源照片，其余照片都在计划里", active not in planned and set(planned) == set(others) and bool(plan.get("plan_id")), t0,
              f"将修改 {plan.get('will_change')} 张，跳过 {plan.get('skipped')} 张")
        check("批量预演没有改任何照片", all(not differences(starts[i], snapshot(i)) for i in others), t0)

        t0 = time.monotonic()
        will = [i for i in others if planned.get(i, {}).get("will_change")]
        result = service.batch_apply(plan["plan_id"]) if plan.get("plan_id") else {}
        batch_id = result.get("batch_id") or ""
        check("批量应用：计划内的照片都已修改并验证", result.get("changed") == len(will) and not result.get("stopped_early_at")
              and all(r.get("verified") for r in result.get("results", [])), t0, f"batch_id={batch_id}")
        for pid in others:
            t1 = time.monotonic()
            now = snapshot(pid)
            want = float(starts[pid]["Exposure2012"]) + (delta if pid in will else 0.0)
            other_keys = {k: v for k, v in starts[pid].items() if k != "Exposure2012"}
            diff = differences(other_keys, now)
            check(f"  {names[pid]}：曝光 {float(starts[pid]['Exposure2012']):+.2f} → {want:+.2f}，其他参数不变",
                  close(now.get("Exposure2012"), want) and not diff, t1, f"其他参数变了：{diff[:8]}" if diff else "")

        t0 = time.monotonic()
        restored = service.restore(batch_id) if batch_id else {"problems": ["没有批次"]}
        ok = check("整批还原：没有遗留问题", not restored.get("problems"), t0, str(restored.get("problems"))[:160] if restored.get("problems") else "")
        for pid in others:
            t1 = time.monotonic()
            diff = differences(starts[pid], snapshot(pid))
            check(f"  {names[pid]}：回到初始快照", not diff, t1, f"不一致：{diff[:8]}" if diff else "")
        if ok:
            batch_id = ""
    except Exception as e:  # noqa: BLE001 - 任何异常都算失败，然后走收尾
        check(f"脚本中途出错：{type(e).__name__}", False, time.monotonic(), str(e)[:200])
    finally:
        # ---- 收尾：恢复到初始快照 + 删除测试版本（无论前面成功与否） ----
        if starts:
            print("\n收尾：恢复到初始快照")
            t0 = time.monotonic()
            if batch_id:
                try:
                    service.restore(batch_id, force=True)
                except Exception as e:  # noqa: BLE001
                    print("  整批还原（收尾）：", str(e)[:120])
            for edit_id in reversed(edits):
                try:
                    service.restore(edit_id, force=True)
                except Exception as e:  # noqa: BLE001
                    print(f"  撤销 {edit_id}：", str(e)[:120])
            for pid, start in starts.items():
                t1 = time.monotonic()
                try:
                    diff = differences(start, snapshot(pid))
                    if diff:                     # 上面的逐条撤销没恢复干净：用“还原到 LrMCP 第一次改动之前”兜底
                        service.restore_original(photo=pid, force=True)
                        diff = differences(start, snapshot(pid))
                    check(f"  最终核对 {names.get(pid, pid[:8])}：{len(start)} 项参数都与初始快照一致", not diff, t1,
                          f"仍不一致：{diff[:10]}（请在 Lightroom 里手动检查这张照片）" if diff else "")
                except Exception as e:  # noqa: BLE001
                    check(f"  最终核对 {names.get(pid, pid[:8])}", False, t1, f"{type(e).__name__}: {str(e)[:160]}")
            print(f"  恢复用时 {time.monotonic() - t0:.1f}s")
        for name in made_versions:
            t1 = time.monotonic()
            try:
                service.delete_version(name, active)
                left = [v["name"] for v in service.list_versions(active)["versions"]]
                check(f"  删除测试版本 {name}", name not in left, t1)
            except Exception as e:  # noqa: BLE001
                check(f"  删除测试版本 {name}", False, t1, f"{type(e).__name__}: {str(e)[:160]}")
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}（修改记录在临时文件夹：{store_dir}）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
