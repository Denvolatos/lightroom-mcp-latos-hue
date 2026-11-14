# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.2.0 照片库真机检查（无窗口、不调用模型，不属于 pytest）。只用测试资源：
  来源 = D:\ceshi\sd_sim（含 DCIM\100MSDCF 的测试照片），照片库 = D:\ceshi\lib_120，目录 = 路径含 ceshi 的测试目录。
  写入前核对目录路径与照片库路径都含 ceshi，否则停止。Lightroom 接口无法删除已加入的照片，事后需手动移除。
  ① 按拍摄日期导入 ② 再导一次应全部判重 ③ 另一个文件夹里“改名的相同内容”应判重 ④ 图库字段（含 size/label/edited/added_at）
用法：python app/tests/live_library_v120_check.py <报告输出 json 路径>
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import import_service as isv  # noqa: E402
import photo_library as pl  # noqa: E402
from lr_service import LrService  # noqa: E402
from preview import PreviewServer  # noqa: E402

CESHI = Path(r"D:\ceshi")
SD = CESHI / "sd_sim"
SD2 = CESHI / "sd_sim2" / "dup"
BASE = CESHI / "lib_120"


class Settings:
    data = {"base_folder": str(BASE)}


def wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def main(out: Path) -> int:
    lr = LrService()
    assert lr.start(), lr.start_error
    assert lr.wait_connected(45), "插件未连接"
    st = lr._bridge.call("status", {}, timeout=10)
    cat = str(st.get("catalog_path", ""))
    print("目录:", cat, "| 插件版本:", lr.plugin_version)
    if "ceshi" not in cat.lower() or "ceshi" not in str(BASE).lower():
        print("路径不含 ceshi，停止")
        lr.stop()
        return 2
    rep = {"catalog": cat, "plugin": lr.plugin_version}
    events = []
    svc = isv.ImportService(Settings(), lr, events.append)

    def run(label, source):
        assert svc.set_source(str(source))["ok"]
        assert wait(lambda: svc.stage == "ready", 60), "扫描未完成"
        info = svc.prepare()
        slim = {k: info.get(k) for k in ("found", "date_summary", "date_more", "duplicates", "to_copy", "can_start", "errors")}
        print(label, "确认信息:", json.dumps(slim, ensure_ascii=False))
        res = None
        if info.get("can_start"):
            assert svc.start(create_base=True)["ok"]
            assert wait(lambda: svc.stage == "done", 300), "导入未完成"
            res = svc.state()["result"]
            print(label, "结果:", json.dumps({"counts": res.get("counts"), "problems": res.get("problems")}, ensure_ascii=False))
        svc.close()
        rep[label] = {"info": slim, "result": res}
        return info, res

    run("第一次导入", SD)
    folders = sorted(str(p.relative_to(BASE)) for p in BASE.rglob("*") if p.is_dir())
    files = sorted(str(p.relative_to(BASE)) for p in BASE.rglob("*") if p.is_file())
    rep["folders"], rep["files"] = folders, files
    print("库内文件夹:", folders, "| 文件数:", len(files))
    run("第二次导入", SD)
    # 改名的相同内容 -> 判重
    SD2.mkdir(parents=True, exist_ok=True)
    src = next(p for p in SD.rglob("*.JPG"))
    shutil.copy2(src, SD2 / "renamed_copy.jpg")
    run("改名重复", SD2.parent)
    files2 = sorted(str(p.relative_to(BASE)) for p in BASE.rglob("*") if p.is_file())
    rep["files_after_dups"] = len(files2)
    # 图库字段
    server = PreviewServer(pl.ThumbStore())
    server.start()
    lib = pl.PhotoLibrary(Settings(), lr, events.append, server, run_async=lambda fn: fn(), dirty_delay=1.0)
    lib.refresh_sync()
    s = lib.state()
    keys = ("name", "group", "captured", "size", "mtime", "label", "edited", "added_at", "rating", "flag", "added")
    rep["gallery"] = {"n": len(s["photos"]), "sort": s.get("sort"), "order": s.get("order"), "state": s.get("state"),
                      "photos": [{k: p.get(k) for k in keys} for p in s["photos"]]}
    print("图库:", s.get("state"), len(s["photos"]), "张 sort=", s.get("sort"), s.get("order"))
    for p in rep["gallery"]["photos"][:8]:
        print("  ", json.dumps(p, ensure_ascii=False))
    server.stop() if hasattr(server, "stop") else None
    lr.stop()
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
