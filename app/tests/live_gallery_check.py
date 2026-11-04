# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件内图库真机检查（无窗口、不调用模型，不属于 pytest）。只用测试资源：
  目录 = 路径含 ceshi 的测试目录（E:\\ceshi1\\ceshi1.lrcat），软件文件夹 = D:\\ceshi\\app_library_test；写入前核对两个路径都含 ceshi，否则立即停止。
走后端 PhotoLibrary（Api 的 library_* 只是它的薄封装，由单元测试覆盖），连接真实 Lightroom：
  ① 列照片并分组；② 缩略图分批取全并统计耗时、字节与缓存命中；③ 选 1 张/3 张/带子文件夹的张，读回 Lightroom 实际选区核对；
  ④ 把 D:\\ceshi\\DSC08238.ARW 复制到 app_library_test\\new_test\\ -> 标“尚未加入” -> 加入 Lightroom -> 变为已加入；
  ⑥ 对 1 张照片做一次小调整（高光 -10，EditService）-> 缩略图缓存失效并重新取 -> 撤销并核对数值回到测试前 -> 缩略图再次刷新。
无论中途是否出错，最后都撤销调整并核对该照片的全部调整参数、所有照片的星级与旗标回到测试前。
Lightroom 接口无法删除已加入的照片：④ 会往测试目录多一张（new_test\\DSC08238.ARW），事后需手动移除。
用法：python app/tests/live_gallery_check.py <报告输出 json 路径>
"""
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import photo_library as pl  # noqa: E402
from lr_service import LrService  # noqa: E402
from preview import PreviewServer  # noqa: E402

CESHI = Path(r"D:\ceshi")
BASE = CESHI / "app_library_test"
NEW_SRC = CESHI / "DSC08238.ARW"
NEW_DIR = BASE / "new_test"


class Settings:
    data = {"base_folder": str(BASE)}


def meta_of_all(lr):
    r = lr.library_list(str(BASE), 0, 500)
    return {p["id"]: (p.get("rating"), p.get("flag")) for p in r["photos"]}


def drain(lib):
    n = 0
    while lib.process_thumbs_once():
        n += 1
    return n


def main(report_path: Path) -> int:
    lr = LrService()
    assert lr.start(), lr.start_error
    assert lr.wait_connected(45), "插件未连接"
    status = lr._bridge.call("status", {}, timeout=10)
    cat = str(status.get("catalog_path", ""))
    print("目录:", cat, "| 插件:", lr.plugin_version, "| Lightroom:", status.get("lightroom_version"))
    if "ceshi" not in cat.lower() or "ceshi" not in str(BASE).lower():
        print("目录或软件文件夹路径不含 ceshi，停止。")
        lr.stop()
        return 2
    assert lr.readonly_error() is None, "只读开关开着"
    report = {"catalog": cat, "plugin": lr.plugin_version, "lightroom": status.get("lightroom_version")}
    events = []
    server = PreviewServer(pl.ThumbStore())
    server.start()
    lib = pl.PhotoLibrary(Settings(), lr, events.append, server, run_async=lambda fn: fn(), dirty_delay=1.0)
    before_meta = meta_of_all(lr)
    edited = {"id": None, "edit_id": None, "before": None}
    try:
        # ① 列照片
        t0 = time.perf_counter()
        lib.refresh_sync()
        t_list = round(time.perf_counter() - t0, 3)
        s = lib.state()
        groups = {}
        for p in s["photos"]:
            groups.setdefault(p["group"], []).append(p["name"])
        raw = lr.library_list(str(BASE), 0, 3)["photos"][:2]
        report["list"] = {"seconds": t_list, "state": s["state"], "total": s["total"], "in_catalog": s["in_catalog"], "not_added": s["not_added"],
                          "missing": s["missing"], "groups": {k: len(v) for k, v in groups.items()}, "sample_raw": raw,
                          "sample_public": s["photos"][:2]}
        print("① 列照片", report["list"]["seconds"], "秒", report["list"]["total"], "张", report["list"]["groups"])
        ids = [p["id"] for p in s["photos"]]
        root = [p["id"] for p in s["photos"] if p["group"] == pl.GROUP_ROOT]
        sub = [p["id"] for p in s["photos"] if p["group"] == "test_batch"]
        # ② 缩略图
        t0 = time.perf_counter()
        r = lib.request_thumbs(ids)
        batches = drain(lib)
        first_failed = dict(lib.state()["failed"])
        t_thumbs = round(time.perf_counter() - t0, 2)
        st = lib.state()
        urls = st["thumbs"]
        sizes = {}
        for i in ids[:3]:
            if i in urls:
                with urllib.request.urlopen(urls[i], timeout=10) as resp:
                    sizes[i] = len(resp.read())
        r2 = lib.request_thumbs(ids)
        report["thumbs"] = {"requested": len(ids), "batches": batches, "seconds": t_thumbs, "got": len(urls), "failed": st["failed"], "failed_before_auto_retry_state": first_failed,
                            "total_bytes": lib.store.total_bytes, "per_photo_bytes_min_max": [min((len(lib.store.peek(i)["bytes"]) for i in urls), default=0),
                                                                                           max((len(lib.store.peek(i)["bytes"]) for i in urls), default=0)],
                            "http_fetch_sizes_ok": sizes, "second_request_pending": r2["pending"], "stats": dict(lib.stats),
                            "hit_rate": lib.cache_hit_rate()}
        print("② 缩略图", report["thumbs"]["got"], "/", len(ids), "张", t_thumbs, "秒", batches, "批", report["thumbs"]["total_bytes"], "字节")

        # ③ 选中
        def read_sel():
            a = lr.selected_all(50) or {}
            return {"ids": [p["id"] for p in a.get("photos", [])], "active": a.get("active_id"), "count": a.get("count")}
        sel_report = []
        for label, pick, act in (("单张(根)", [root[0]], root[0]), ("三张(根2+子1)", [root[1], root[2], sub[0]], sub[0]),
                                 ("子文件夹单张", [sub[3]], sub[3]), ("三张(子)", sub[1:4], sub[2]), ("根单张(切回)", [root[4]], root[4])):
            t0 = time.perf_counter()
            res = lib.select(pick, act)
            dt = round(time.perf_counter() - t0, 2)
            actual = read_sel()
            ok = set(actual["ids"]) == set(pick) and actual["active"] == act and set(res["selected"]) == set(pick)
            sel_report.append({"case": label, "seconds": dt, "ok": ok, "status": res["status"], "message": res["message"], "actual": actual})
            print("③", label, dt, "秒", "一致" if ok else "不一致", res["status"])
        report["select"] = sel_report
        report["select_on_selected_calls_note"] = "on_selected 为空（后端单独运行）"

        # ④ 尚未加入
        src_before = (NEW_SRC.stat().st_size, NEW_SRC.stat().st_mtime_ns)
        NEW_DIR.mkdir(exist_ok=True)
        dest = NEW_DIR / NEW_SRC.name
        if not dest.exists():
            shutil.copy2(NEW_SRC, dest)
        lib.refresh_sync()
        s = lib.state()
        flagged = [p for p in s["photos"] if not p["added"]]
        report["not_added"] = {"before_not_added": s["not_added"], "flagged": [(p["name"], p["group"]) for p in flagged]}
        t0 = time.perf_counter()
        add = lib.add_missing()
        t_add = round(time.perf_counter() - t0, 2)
        astate = lib.add_state()
        s = lib.state()
        report["not_added"].update({"add_result": add, "add_seconds": t_add, "add_state": astate, "after_not_added": s["not_added"],
                                    "after_total": s["total"], "new_group_names": sorted({p["group"] for p in s["photos"]}),
                                    "source_unchanged": (NEW_SRC.stat().st_size, NEW_SRC.stat().st_mtime_ns) == src_before})
        print("④ 加入", add, t_add, "秒", (astate or {}).get("counts"), "之后尚未加入", s["not_added"], "总数", s["total"])
        ids = [p["id"] for p in s["photos"]]

        # ⑥ 调整 -> 缩略图失效并重取 -> 撤销
        target = next(p for p in s["photos"] if p["name"] == "DSC08205.JPG" and p["group"] == pl.GROUP_ROOT)
        pid = target["id"]
        edited["id"] = pid
        lib.request_thumbs([pid], retry=True)
        drain(lib)
        orig_bytes = lib.store.peek(pid)["bytes"]
        dev_before = lr.develop_of(pid)
        edited["before"] = dev_before
        hl = dev_before["settings"]["Highlights2012"]
        res = lr.apply_settings({"Highlights2012": hl - 10}, "图库真机测试：小调整（会撤销）", "图库测试", pid)
        edited["edit_id"] = res.get("edit_id")
        dev_mid = lr.develop_of(pid)["settings"]["Highlights2012"]
        n_inv = lib.invalidate_thumbs([pid])
        gone = pid not in lib.state()["thumbs"]
        changed_after, waited = None, 0.0
        t0 = time.perf_counter()
        for _ in range(8):
            time.sleep(1.2)
            drain(lib)
            e = lib.store.peek(pid)
            if e is not None:
                changed_after = e["bytes"] != orig_bytes
                waited = round(time.perf_counter() - t0, 2)
                if changed_after:
                    break
                lib.invalidate_thumbs([pid])
        mid_bytes = len(lib.store.peek(pid)["bytes"]) if lib.store.peek(pid) else None
        report["adjust"] = {"photo": target["name"], "highlights_before": hl, "highlights_after_edit": dev_mid, "invalidated_entries": n_inv,
                            "cache_dropped": gone, "thumb_refetched_bytes_differ": changed_after, "seconds_until_refetched": waited,
                            "orig_bytes": len(orig_bytes), "mid_bytes": mid_bytes}
        print("⑥ 调整", hl, "->", dev_mid, "| 缓存已丢弃", gone, "| 新缩略图字节不同", changed_after, "用时", waited)
        u = lr.undo(edited["edit_id"])
        edited["edit_id"] = None if u.get("ok") else edited["edit_id"]
        dev_after = lr.develop_of(pid)
        lib.invalidate_thumbs([pid])
        time.sleep(1.2)
        drain(lib)
        back = lib.store.peek(pid)
        report["adjust"].update({"undo_ok": u.get("ok"), "undo_message": u.get("message"), "settings_equal_to_before": dev_after["settings"] == dev_before["settings"],
                                 "highlights_after_undo": dev_after["settings"]["Highlights2012"],
                                 "thumb_after_undo_bytes": len(back["bytes"]) if back else None,
                                 "thumb_after_undo_equals_original": bool(back and back["bytes"] == orig_bytes)})
        print("⑥ 撤销", u.get("ok"), "设置还原", report["adjust"]["settings_equal_to_before"], "缩略图字节", report["adjust"]["thumb_after_undo_bytes"],
              "与原缩略图相同", report["adjust"]["thumb_after_undo_equals_original"])
    finally:
        if edited["edit_id"]:
            try:
                print("兜底撤销", lr.undo(edited["edit_id"], True))
            except Exception as e:                       # noqa: BLE001
                print("兜底撤销失败", e)
        final = {}
        if edited["id"] and edited["before"]:
            now = lr.develop_of(edited["id"])
            final["develop_settings_equal_to_before"] = now["settings"] == edited["before"]["settings"]
            final["develop_hsl_equal_to_before"] = now.get("hsl") == edited["before"].get("hsl")
            final["local_adjustments_equal"] = now.get("has_local_adjustments") == edited["before"].get("has_local_adjustments")
        after_meta = meta_of_all(lr)
        final["rating_flag_unchanged_for_all_original_photos"] = all(after_meta.get(k) == v for k, v in before_meta.items())
        final["photos_before"], final["photos_after"] = len(before_meta), len(after_meta)
        report["final"] = final
        print("最终核对:", json.dumps(final, ensure_ascii=False))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        server.stop()
        lr.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
