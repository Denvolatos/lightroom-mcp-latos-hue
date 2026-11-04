# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导出功能真机检查（无窗口、不调用模型，不属于 pytest）。只用测试资源：
目录路径须含 ceshi，输出文件夹固定为 D:\\ceshi\\export_test2（路径须含 ceshi），否则立即停止。
导出的是 Lightroom 当前选中的测试照片；不做“原始尺寸”导出。
用法：python app/tests/live_export_check.py <报告输出 json 路径>
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export_service as es  # noqa: E402
from lr_service import LrService  # noqa: E402

OUT = Path(r"D:\ceshi\export_test2")


class Settings:
    def __init__(self):
        import settings as st
        self.data = st.defaults()

    def update(self, changes, **k):
        self.data.update(changes)
        return {"ok": True}


def tiff_info(path):
    """位深与尺寸：用 PIL（若有）；PIL 读不了 16 位多通道 TIFF 时回退到手工解析 IFD。"""
    import struct
    with open(path, "rb") as f:
        data = f.read(1 << 20)
    bo = "<" if data[:2] == b"II" else ">"
    ifd = struct.unpack(bo + "I", data[4:8])[0]
    n = struct.unpack(bo + "H", data[ifd:ifd + 2])[0]
    out = {}
    for i in range(n):
        e = data[ifd + 2 + 12 * i: ifd + 14 + 12 * i]
        tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
        if typ == 3 and cnt == 1:
            out[tag] = struct.unpack(bo + "H", e[8:10])[0]
        elif typ == 4 and cnt == 1:
            out[tag] = struct.unpack(bo + "I", e[8:12])[0]
        elif tag == 258 and typ == 3:
            off = struct.unpack(bo + "I", e[8:12])[0]
            out[tag] = struct.unpack(bo + "H", data[off:off + 2])[0] if cnt > 1 else out.get(tag)
    return {"width": out.get(256), "height": out.get(257), "bits": out.get(258), "compression": out.get(259)}


def jpeg_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def main(report_path: Path) -> int:
    lr = LrService()
    assert lr.start(), lr.start_error
    assert lr.wait_connected(45), "插件未连接"
    status = lr._bridge.call("status", {}, timeout=10)
    cat = str(status.get("catalog_path", ""))
    print("目录:", cat, "| 插件版本:", lr.plugin_version, "| Lightroom:", status.get("lightroom_version"))
    if "ceshi" not in cat.lower() or "ceshi" not in str(OUT).lower():
        print("目录或输出文件夹路径不含 ceshi，停止。")
        lr.stop()
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    events = []
    svc = es.ExportService(Settings(), lr, events.append, timeout=120)
    r = svc.set_folder(str(OUT))
    assert r["ok"], r
    ds = svc.dialog_state()
    print("对话框状态:", json.dumps({k: ds[k] for k in ("connected", "photo", "folder", "can_export", "reason")}, ensure_ascii=False))
    report = {"catalog": cat, "plugin": lr.plugin_version, "lightroom": status.get("lightroom_version"), "photo": ds.get("photo"),
              "runs": []}
    if not ds["can_export"]:
        print("无法导出：", ds["reason"])
        lr.stop()
        return 3

    def run(label, opts):
        svc.close()
        before = set(os.listdir(OUT))
        t0 = time.perf_counter()
        r = svc.export(opts)
        assert r["ok"], r
        end = time.time() + 130
        while time.time() < end and svc.state()["stage"] != "done":
            time.sleep(0.1)
        dt = time.perf_counter() - t0
        res = svc.state().get("result", {})
        new = sorted(set(os.listdir(OUT)) - before)
        item = {"label": label, "opts": opts, "seconds": round(dt, 2), "result": res, "new_files": new}
        if res.get("status") == "exported":
            path = OUT / res["file"]
            item["bytes"] = path.stat().st_size
            item["ext"] = path.suffix
            if opts["format"] == "tiff":
                item["tiff"] = tiff_info(path)
            else:
                item["jpeg_size"] = jpeg_size(path)
        print(label, "->", json.dumps({k: item.get(k) for k in ("seconds", "bytes", "ext", "tiff", "jpeg_size", "new_files")}, ensure_ascii=False),
              res.get("status"), res.get("message"))
        report["runs"].append(item)
        return item

    base = {"size": 1024, "quality": 92, "bit_depth": 16, "metadata": "minimal"}
    run("JPEG 1024", {**base, "format": "jpeg"})
    run("TIFF 16 位 1024", {**base, "format": "tiff", "bit_depth": 16})
    run("TIFF 8 位 1024", {**base, "format": "tiff", "bit_depth": 8})
    run("JPEG 1024 同名再导", {**base, "format": "jpeg"})
    # reveal 检查（用假的显示函数，不打开资源管理器）：只对本次结果文件有效
    shown = []
    svc._reveal = shown.append
    rv = svc.reveal_last()
    report["reveal"] = {"ok": rv["ok"], "target": shown[0] if shown else None, "is_last_result": bool(shown) and os.path.basename(shown[0]) == report["runs"][-1]["result"].get("file")}
    print("reveal:", report["reveal"])
    svc.close()
    shown.clear()
    report["reveal_after_close_state"] = svc.reveal_last()["ok"]          # 结果仍在后端记录里（文件在），应为 True，且路径同上
    # 拒绝项：用后端接口再验证两种页面不可控的情况
    report["refused_bad_options"] = svc.export({**base, "format": "png"})["ok"] is False
    report["refused_bad_size"] = svc.export({**base, "format": "jpeg", "size": 100})["ok"] is False
    report["events"] = [e.get("type") + ":" + str(e.get("state") or e.get("status")) for e in events]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lr.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
