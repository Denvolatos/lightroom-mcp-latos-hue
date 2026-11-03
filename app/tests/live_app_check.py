"""真实整体检查（无窗口；会消耗订阅额度，不属于 pytest）。
用法：python app/tests/live_app_check.py <connect|read|write|all> [输出json]
- connect：不调用模型。测预热到“已连接”的时间、强制结束 claude 后的自动恢复时间、失效公告清理。
- read：一个只读问题，记录常驻会话的分阶段耗时。
- write：只在目录路径含 ceshi 的测试照片上做一次小调整（逐项确认=开，程序代替用户点“同意”），再撤销并核对数值回到测试前。
"""
import json
import subprocess
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
        st = api.status()
        if st["state"] == state:
            return round(time.monotonic() - t0, 1), st
        time.sleep(0.2)
    return None, api.status()


def ask(api, win, text, confirm, approve=False, timeout=180):
    win.events.clear()
    t0 = time.monotonic()
    r = api.send(text, confirm)
    assert r.get("ok"), r
    if approve:
        c = win.wait(lambda e: e["type"] == "confirm", 90)
        print("  确认卡片:", None if c is None else [(i["label"], i["from"], i["to"]) for i in c["items"]], flush=True)
        if c:
            api.answer(c["id"], True)
    done = win.wait(lambda e: e["type"] == "done", timeout)
    return done, round(time.monotonic() - t0, 1)


def main() -> None:
    mode = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("live_app_result.json")
    res = {}
    api = appmain.Api()
    win = FakeWindow()
    api._window = win
    t0 = time.monotonic()
    api._start_background()
    t_conn, st = wait_state(api, "connected", 60)
    res["warmup_to_connected_s"] = t_conn
    print("预热到已连接(秒):", t_conn, "| 插件版本", st.get("plugin_version"), "| 状态", st["text"], flush=True)
    time.sleep(5)   # 等第一次读取选中照片
    print("当前照片:", api.status().get("photo"), flush=True)
    try:
        if mode in ("connect", "all"):
            sess = api._session
            old_pid = sess._proc.pid
            t1 = time.monotonic()
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(old_pid)], capture_output=True)
            print("已强制结束 claude 进程树，等待自动恢复…", flush=True)
            flipped, _ = wait_state(api, "connecting", 5)      # 先确认状态确实掉下来了
            res["status_dropped_after_s"] = flipped
            t_back, st = wait_state(api, "connected", 90)
            res["auto_recover_s"] = None if t_back is None else round(time.monotonic() - t1, 1)
            res["recover_new_pid"] = sess._proc.pid != old_pid if sess._proc else None
            print("强制结束后自动恢复到已连接(秒):", res["auto_recover_s"], "| 恢复动作:", api._backend.events, flush=True)
        if mode in ("read", "all"):
            done, wall = ask(api, win, "读取当前照片的曝光和高光值，只回答两个数字。", True)
            t = api._session.last_timing
            res["read_turn"] = {"wall_s": wall, **t, "tokens": done and done.get("tokens")}
            print("只读轮:", json.dumps(t, ensure_ascii=False), flush=True)
        if mode in ("write",):
            lr = api._lr
            catalog = lr._bridge.call("status", {}).get("catalog_path", "")
            print("目录:", catalog, flush=True)
            assert "ceshi" in catalog.lower(), "目录不是测试目录，停止"
            keys = ["Exposure2012", "Highlights2012", "Shadows2012", "Contrast2012", "Temperature", "Tint"]
            def snap():
                s = lr._bridge.call("get_develop", {"photo": "selected"})["settings"]
                return {k: s.get(k) for k in keys}
            before = snap()
            print("测前:", before, flush=True)
            try:
                done, wall = ask(api, win, "将曝光提高 0.1。", True, approve=True)
                res["write_turn"] = {"wall_s": wall, **(api._session.last_timing or {})}
                rows = [r for r in api._tracker.snapshot()]
                print("表格:", [(r["label"], r["before"], r["after"], r["status"]) for r in rows], flush=True)
                res["rows"] = [(r["label"], r["before"], r["after"], r["status"]) for r in rows]
                for r in rows:
                    if r["status"] == "已应用" and r["edit_id"]:
                        u = api.undo(r["edit_id"], False)
                        print("撤销:", u, flush=True)
            finally:
                after = snap()
                print("测后:", after, flush=True)
                res["restored_equal"] = after == before
                if after != before:
                    print("数值未回到测试前，尝试还原到原始状态", api.restore_original(False), snap(), flush=True)
        if mode in ("all", "connect"):
            api.reset()
            time.sleep(1)
            res["after_reset"] = {"alive": api._session.alive, "session_id": api._session.session_id,
                                  "rows": len(api._backend.rows())}
            print("新对话后:", res["after_reset"], flush=True)
    finally:
        api._shutdown()
        time.sleep(1)
        left = [p.name for p in (Path.home() / "LrMcp" / "servers").glob("*.txt")]
        res["announcements_after_exit"] = left
        print("退出后残留公告:", left, flush=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


main()
