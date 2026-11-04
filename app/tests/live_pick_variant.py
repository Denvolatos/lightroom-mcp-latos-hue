# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 挑片真机变体检查（会消耗订阅额度，不属于 pytest）：只做一次挑片，不写入；核对 AI 没有改动任何星级/旗标。
用法：python app/tests/live_pick_variant.py <结果 json> <criterion> <count> [自定义文字]
目录路径须含 ceshi；须事先在 Lightroom 中选好测试照片。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as appmain  # noqa: E402
from live_pick_check import FakeWindow, wait_state  # noqa: E402


def main() -> None:
    out, crit, count = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    custom = sys.argv[4] if len(sys.argv) > 4 else ""
    res = {"criterion": crit, "count": count, "custom": custom}
    api = appmain.Api()
    win = FakeWindow()
    api._window = win
    api._start_background()
    lr = api._lr
    before = {}
    try:
        assert wait_state(api, "connected", 60) is not None, "未连接"
        catalog = lr._bridge.call("status", {}).get("catalog_path", "")
        assert "ceshi" in catalog.lower(), "目录不是测试目录，停止"
        time.sleep(4)
        sel = api.selection_state()
        res["selected"] = [p["name"] for p in sel["photos"]]
        for p in sel["photos"]:
            m = lr.metadata_of(p["id"])["metadata"]
            before[p["id"]] = (m["rating"], m["flag"])
        assert api.pick_prepare()["ok"]
        t0 = time.monotonic()
        s = api.pick_start({"criterion": crit, "custom": custom, "count": count})
        assert s["ok"], s
        done = win.wait(lambda e: e["type"] == "pick_done", 200)
        res["wall_s"] = round(time.monotonic() - t0, 1)
        res["pick"] = done
        print(json.dumps(done, ensure_ascii=False)[:1800], flush=True)
        print("用时", res["wall_s"], "token", done and done.get("tokens"), "费用", done and done.get("cost"), flush=True)
    finally:
        after = {}
        for pid in before:
            m = lr.metadata_of(pid)["metadata"]
            after[pid] = (m["rating"], m["flag"])
        res["ratings_unchanged_by_ai"] = after == before
        print("AI 没有改动星级/旗标:", res["ratings_unchanged_by_ai"], flush=True)
        api._shutdown()
        time.sleep(1)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
