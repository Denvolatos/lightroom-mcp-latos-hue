"""AI 挑片真机检查（无窗口；会消耗订阅额度，不属于 pytest）。只用测试资源：
- 目录路径须含 ceshi，否则立即停止；
- 须事先在 Lightroom 里选中 3 张测试照片（开发桥脚本 select_three.lua）；
- 真实调用模型 1 次（3 张、综合观感、前 3 名）；
- 然后对其中 2 张用后端接口"应用建议"写星级/旗标，核对 Lightroom 里确实变了，再"撤销这次写入"，核对回到测试前的值；
- 无论中途是否出错，最后都会核对 3 张照片的星级/旗标与测试前一致，不一致则先 restore、再直接写回测前的值。
用法：python app/tests/live_pick_check.py <结果 json 路径> [缩略图输出目录]
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as appmain  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.events = []
        self.cv = threading.Condition()

    def evaluate_js(self, js):
        prefix = "window.onClaudeEvent && window.onClaudeEvent("
        if js.startswith(prefix):
            with self.cv:
                self.events.append((time.monotonic(), json.loads(js[len(prefix):-1])))
                self.cv.notify_all()

    def wait(self, pred, timeout):
        end = time.monotonic() + timeout
        with self.cv:
            while time.monotonic() < end:
                for t, e in self.events:
                    if pred(e):
                        return e
                self.cv.wait(0.2)
        return None


def wait_state(api, state, timeout=60):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if api.status()["state"] == state:
            return round(time.monotonic() - t0, 1)
        time.sleep(0.2)
    return None


def main() -> None:
    out = Path(sys.argv[1])
    thumbs_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    res = {}
    api = appmain.Api()
    win = FakeWindow()
    api._window = win
    api._start_background()
    lr = api._lr
    before = {}
    try:
        res["warmup_to_connected_s"] = wait_state(api, "connected", 60)
        assert res["warmup_to_connected_s"] is not None, "未连接"
        catalog = lr._bridge.call("status", {}).get("catalog_path", "")
        res["catalog"] = catalog
        print("目录:", catalog, flush=True)
        assert "ceshi" in catalog.lower(), "目录不是测试目录，停止"
        time.sleep(4)                                              # 等后台轮询读到选中的照片
        sel = api.selection_state()
        res["selection"] = sel
        print("选中:", sel["count"], [p["name"] for p in sel["photos"]], flush=True)
        assert sel["count"] == 3, "请先选中 3 张测试照片"
        for p in sel["photos"]:
            m = lr.metadata_of(p["id"])["metadata"]
            before[p["id"]] = {"rating": m["rating"], "flag": m["flag"], "keywords": m["keywords"], "title": m["title"]}
        res["before"] = before
        print("测前:", before, flush=True)

        r = api.pick_prepare()
        assert r["ok"], r
        time.sleep(4)                                              # 缩略图
        res["thumbs"] = api.pick_state()["thumbs"]
        if thumbs_dir:
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            for p in sel["photos"]:
                raw, _ = lr.preview_bytes(p["id"], 256)
                (thumbs_dir / f"{p['name']}.jpg").write_bytes(raw)
        t0 = time.monotonic()
        s = api.pick_start({"criterion": "overall", "count": "top3"})
        assert s["ok"], s
        done = win.wait(lambda e: e["type"] == "pick_done", 200)
        res["pick_wall_s"] = round(time.monotonic() - t0, 1)
        assert done is not None, "没有收到 pick_done"
        res["pick"] = done
        res["timing"] = api._provider.session.last_timing
        print("挑片结果:", json.dumps(done, ensure_ascii=False)[:1500], flush=True)
        print("用时/Token/费用:", res["pick_wall_s"], done.get("tokens"), done.get("cost"), flush=True)
        if done["status"] not in ("ok", "partial"):
            return

        # ---- 写入两张 ----
        items = api.pick_apply_prepare()
        res["checklist"] = items
        print("确认清单:", json.dumps(items, ensure_ascii=False), flush=True)
        assert items["ok"]
        changed = [i for i in items["items"] if i["changed"]][:2]
        if len(changed) < 2:
            res["note"] = "建议与现有值相同的照片太多，无法写入 2 张；只写 %d 张" % len(changed)
        ids = [i["photo_id"] for i in changed]
        r = api.pick_apply_confirm(ids)
        assert r["ok"], r
        wd = win.wait(lambda e: e["type"] == "pick_apply_done", 60)
        res["apply"] = wd
        print("写入结果:", json.dumps(wd, ensure_ascii=False), flush=True)
        after_write = {}
        for pid in ids:
            m = lr.metadata_of(pid)["metadata"]
            after_write[pid] = {"rating": m["rating"], "flag": m["flag"], "keywords": m["keywords"], "title": m["title"]}
        res["after_write"] = after_write
        want = {i["photo_id"]: (i["new_rating"], i["new_flag"]) for i in changed}
        res["write_matches_suggestion"] = all((after_write[p]["rating"], after_write[p]["flag"]) == want[p] for p in ids)
        res["keywords_title_untouched"] = all(after_write[p]["keywords"] == before[p]["keywords"] and after_write[p]["title"] == before[p]["title"] for p in ids)
        print("写后:", after_write, "| 与建议一致:", res["write_matches_suggestion"], "| 关键词/标题未动:", res["keywords_title_untouched"], flush=True)

        u = api.pick_apply_undo(False)
        res["undo"] = u
        print("撤销:", json.dumps(u, ensure_ascii=False), flush=True)
    finally:
        # 无论如何都要核对并还原
        bad = []
        for pid, b in before.items():
            m = lr.metadata_of(pid)["metadata"]
            if (m["rating"], m["flag"]) != (b["rating"], b["flag"]):
                bad.append(pid)
        res["not_restored_after_undo"] = bad
        for pid in bad:
            try:
                lr.set_rating_flag(pid, before[pid]["rating"], before[pid]["flag"], "测试收尾：写回测前的值")
            except Exception as e:  # noqa: BLE001
                print("收尾写回失败", pid, e, flush=True)
        final = {}
        for pid, b in before.items():
            m = lr.metadata_of(pid)["metadata"]
            final[pid] = {"rating": m["rating"], "flag": m["flag"], "keywords": m["keywords"], "title": m["title"]}
        res["final"] = final
        res["final_equals_before"] = final == before
        print("最终与测前一致:", res["final_equals_before"], "| 撤销后未还原的:", bad, flush=True)
        api._shutdown()
        time.sleep(1)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
