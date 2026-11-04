# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导入功能真机检查（无窗口、不调用模型，不属于 pytest）。只用测试资源：
  “存储卡” = D:\\ceshi\\sd_sim（从 D:\\ceshi 里复制几张测试照片得到），软件文件夹 = D:\\ceshi\\app_library_test，
  目录 = 路径含 ceshi 的测试目录。写入前核对目录路径和软件文件夹路径都含 ceshi，否则立即停止。
用法：python app/tests/live_import_check.py <报告输出 json 路径>
不动 D:\\ceshi 里的原有文件（只读它们来复制出“存储卡”）；Lightroom 接口无法删除已加入的照片，事后需手动移除。
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import import_service as isv  # noqa: E402
import importer as imp  # noqa: E402
from lr_service import LrService  # noqa: E402

CESHI = Path(r"D:\ceshi")
SD = CESHI / "sd_sim" / "DCIM" / "100MSDCF"
BASE = CESHI / "app_library_test"
PICK = ["DSC08151.ARW", "DSC08151.JPG", "DSC08238.JPG", "DSC08206.ARW"]      # 2 张 ARW、2 张 JPG；DSC08151 是 RAW+JPEG 同名对


EXTRA = ["DSC08245.ARW", "DSC08244.JPG", "DSC08205.JPG"]


class Settings:
    data = {"base_folder": str(BASE)}


def sig(p: Path):
    s = p.stat()
    return (s.st_size, s.st_mtime_ns)


def wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def main(report_path: Path) -> int:
    lr = LrService()
    assert lr.start(), lr.start_error
    assert lr.wait_connected(45), "插件未连接"
    status = lr._bridge.call("status", {}, timeout=10)
    cat = str(status.get("catalog_path", ""))
    print("目录:", cat, "| 插件版本:", lr.plugin_version, "| Lightroom:", status.get("lightroom_version"))
    if "ceshi" not in cat.lower() or "ceshi" not in str(BASE).lower():
        print("目录或软件文件夹路径不含 ceshi，停止。")
        lr.stop()
        return 2
    assert lr.readonly_error() is None, "只读开关开着"
    report = {"catalog": cat, "plugin": lr.plugin_version, "lightroom": status.get("lightroom_version"), "files": []}
    # 1. 准备“存储卡”：从 D:\ceshi 的原文件复制（原文件只读）
    originals = {n: sig(CESHI / n) for n in PICK}
    SD.mkdir(parents=True, exist_ok=True)
    for n in PICK:
        if not (SD / n).exists():
            shutil.copy2(CESHI / n, SD / n)
    sd_before = {n: sig(SD / n) for n in PICK}
    print("存储卡模拟目录文件:", {n: sd_before[n][0] for n in PICK})

    timings = {}
    real_copy, real_import = imp.copy_one, lr.import_photo

    def timed_copy(src, folder, **kw):
        t = time.perf_counter()
        r = real_copy(src, folder, **kw)
        timings.setdefault(Path(src).name, {})["copy_s"] = round(time.perf_counter() - t, 3)
        return r

    def timed_import(path):
        t = time.perf_counter()
        try:
            r = real_import(path)
        finally:
            timings.setdefault(Path(path).name.split("_")[0] if False else Path(path).name, {})["import_s"] = round(time.perf_counter() - t, 3)
        report["files"].append({"name": Path(path).name, "result": {k: r.get(k) for k in ("status", "already", "photo_id", "name", "photo", "message")}})
        return r

    imp.copy_one = timed_copy
    lr.import_photo = timed_import
    events = []
    svc = isv.ImportService(Settings(), lr, events.append)

    def run_once(label, category):
        assert svc.set_source(str(SD.parent.parent))["ok"]            # 来源 = sd_sim 根（递归找到 DCIM\100MSDCF）
        assert wait(lambda: svc.stage == "ready", 30)
        info = svc.prepare(category)
        print(label, "确认信息:", json.dumps({k: info[k] for k in ("found", "base", "target", "free_text", "needed_text", "can_start", "errors")}, ensure_ascii=False))
        assert info["can_start"], info["errors"]
        t0 = time.perf_counter()
        r = svc.start(category, create_base=True)
        assert r["ok"], r
        assert wait(lambda: svc.stage == "done", 300)
        total = round(time.perf_counter() - t0, 2)
        res = svc.state()["result"]
        print(label, "结果:", json.dumps({"counts": res["counts"], "problems": res["problems"], "elapsed": res["elapsed"]}, ensure_ascii=False))
        svc.close()
        res = dict(res, lr_calls=list(report["files"]))
        report["files"].clear()
        return res, total

    res1, total1 = run_once("第一次", "test_batch")
    report["run1"] = {"result": res1, "wall_s": total1, "per_file": dict(timings)}
    # 2. 核对：源文件未变、副本存在且大小一致
    dest_dir = BASE / "test_batch"
    checks = {}
    for n in PICK:
        d = dest_dir / n
        checks[n] = {"dest_exists": d.exists(), "size_equal": d.exists() and d.stat().st_size == sd_before[n][0],
                     "sd_unchanged": sig(SD / n) == sd_before[n], "original_unchanged": sig(CESHI / n) == originals[n]}
    report["checks"] = checks
    print("核对:", json.dumps(checks, ensure_ascii=False))
    leftovers = [p.name for p in dest_dir.iterdir() if ".part" in p.name]
    report["part_leftovers"] = leftovers
    # 3. Lightroom 里确有这些照片：再导入应得 already，并取照片信息
    again = {}
    for n in PICK:
        r = real_import(str(dest_dir / n))
        again[n] = {k: r.get(k) for k in ("status", "already", "photo_id", "name", "photo")}
    report["lr_again"] = again
    print("再次加入（应全为 already）:", json.dumps({n: v["status"] for n, v in again.items()}))
    # 4. 整体重跑：同名同大小跳过
    files_before = {p.name for p in dest_dir.iterdir()}
    timings.clear()
    res2, total2 = run_once("第二次", "test_batch")
    report["run2"] = {"result": res2, "wall_s": total2, "per_file": dict(timings)}
    report["rerun_new_files"] = sorted({p.name for p in dest_dir.iterdir()} - files_before)
    # 3. 增量导入：存储卡上又多了 3 张新照片（1 张 ARW、2 张 JPG），已导入的 4 张应被跳过，新的 3 张应为 imported
    for n in EXTRA:
        if not (SD / n).exists():
            shutil.copy2(CESHI / n, SD / n)
    originals.update({n: sig(CESHI / n) for n in EXTRA})
    sd_before.update({n: sig(SD / n) for n in EXTRA})
    timings.clear()
    res3, total3 = run_once("第三次（增量）", "test_batch")
    report["run3"] = {"result": res3, "wall_s": total3, "per_file": dict(timings)}
    report["final_src_unchanged"] = all(sig(SD / n) == sd_before[n] for n in PICK + EXTRA) and all(sig(CESHI / n) == originals[n] for n in PICK + EXTRA)
    imp.copy_one = real_copy
    lr.stop()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("报告:", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
