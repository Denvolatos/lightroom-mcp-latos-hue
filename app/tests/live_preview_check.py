# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""真实预览检查（无窗口、不调用模型，不属于 pytest）。只读为主；写入前确认目录路径含 ceshi。
用法：python app/tests/live_preview_check.py [输出目录]
步骤：取初始预览（计时、核对尺寸与信息条）-> 再取一次（缓存命中）-> 曝光 +0.1（只做一次）-> 等“当前”自动刷新（计时）
      -> 撤销 -> 等刷新（应回到与初始同一条缓存）-> 核对六项数值回到测试前。
"""
import io
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lr_service import LrService  # noqa: E402
from preview import PreviewManager, PreviewServer, PreviewStore  # noqa: E402

KEYS = ["Exposure2012", "Highlights2012", "Shadows2012", "Contrast2012", "Temperature", "Tint"]


def values(lr, pid):
    s = lr.develop_of(pid)["settings"]
    return {k: s.get(k) for k in KEYS}


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    lr = LrService()
    assert lr.start(), lr.start_error
    assert lr.wait_connected(25), "插件未连接"
    status = lr._bridge.call("status", {}, timeout=10)
    print("目录:", status.get("catalog_path"))
    if "ceshi" not in str(status.get("catalog_path", "")).lower():
        print("目录路径不含 ceshi，停止。")
        lr.stop()
        return 2
    events, cv = [], threading.Condition()

    def emit(ev):
        with cv:
            events.append((time.monotonic(), ev))
            cv.notify_all()

    def wait(pred, since, timeout=30):
        end = time.monotonic() + timeout
        with cv:
            while time.monotonic() < end:
                for t, e in events:
                    if t >= since and pred(e):
                        return t, e
                cv.wait(0.1)
        return None, None

    server = PreviewServer(PreviewStore())
    server.start()
    m = PreviewManager(lr, server, emit)
    m.start()
    report = {}
    try:
        detail = lr.selected_detail()
        pid = detail["id"]
        before = values(lr, pid)
        print("测前数值:", before)
        report["before"] = before

        t0 = time.monotonic()
        m.request(0)
        t, ev = wait(lambda e: e["type"] == "preview" and e["state"] == "ok", t0)
        report["first_total_s"] = round(t - t0, 2)
        report["first_fetch_s"] = m.last_fetch_seconds
        print("首次(初始) 总耗时", report["first_total_s"], "其中取图", m.last_fetch_seconds, "尺寸", ev["current"]["w"], ev["current"]["h"], "same", ev["same"])
        print("信息条:", ev["photo"])
        report["info"], report["size"] = ev["photo"], [ev["current"]["w"], ev["current"]["h"]]
        initial_url = ev["initial"]["url"]
        raw0 = urllib.request.urlopen(initial_url, timeout=10).read()
        (out_dir / "initial.jpg").write_bytes(raw0)

        # 缓存命中：同一版本再请求，不应再取图
        fc = m.fetch_count
        t1 = time.monotonic()
        m.refresh()
        report["cache_hit_s"] = round(time.monotonic() - t1, 3)
        report["cache_hit_refetched"] = m.fetch_count != fc
        print("同版本再刷新", report["cache_hit_s"], "s，是否重新取图:", report["cache_hit_refetched"])

        # 写入：曝光 +0.1，只做一次
        res = lr._edits.set_develop({"Exposure2012": before["Exposure2012"] + 0.1}, "预览刷新真实测试", "selected")
        edit_id = res["edit_id"]
        t2 = time.monotonic()
        m.request()                                     # 与界面里“调整已应用”后的触发一致（短防抖）
        t, ev2 = wait(lambda e: e["type"] == "preview" and e["state"] == "ok" and not e.get("loading") and e["same"] is False, t2)
        report["adjust_refresh_s"] = None if t is None else round(t - t2, 2)
        print("调整后“当前”刷新延迟(含防抖):", report["adjust_refresh_s"], "s")
        assert ev2 is not None, "当前未刷新"
        assert ev2["initial"]["url"] == initial_url, "初始图被改变"
        raw1 = urllib.request.urlopen(ev2["current"]["url"], timeout=10).read()
        (out_dir / "adjusted.jpg").write_bytes(raw1)

        # 撤销
        r = lr.undo(edit_id)
        print("撤销:", r["ok"], r["message"])
        t3 = time.monotonic()
        m.request()
        t, ev3 = wait(lambda e: e["type"] == "preview" and e["state"] == "ok" and not e.get("loading") and e["same"] is True, t3)
        report["undo_refresh_s"] = None if t is None else round(t - t3, 2)
        print("撤销后刷新延迟:", report["undo_refresh_s"], "s；current==initial:", None if ev3 is None else ev3["current"]["url"] == initial_url)
        report["undo_matches_initial"] = bool(ev3 and ev3["current"]["url"] == initial_url)
        report["fetch_count"] = m.fetch_count

        after = values(lr, pid)
        print("测后数值:", after)
        report["after"] = after
        report["restored_exactly"] = after == before
        print("数值回到测试前:", after == before)
    finally:
        m.stop()
        lr.stop()
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if report.get("restored_exactly") else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("live_preview_out")))
