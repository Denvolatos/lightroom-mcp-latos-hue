"""修图助手：打开界面，对话框接到本机已登录的 Claude Code 命令行，可查看并调整照片（支持逐项确认与撤销）。

运行：python app/main.py
"""
import json
import sys
import threading
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adjustments import AdjustmentTracker  # noqa: E402
from claude_bridge import ClaudeSession  # noqa: E402
from confirm_hub import ConfirmHub  # noqa: E402
from lr_service import LrService  # noqa: E402

WEB = Path(__file__).resolve().parent / "web" / "index.html"


class Api:
    """页面里用 window.pywebview.api.send(text, confirm) / stop() / reset() / answer(id, allow) /
    undo(edit_id, force) / restore_original(force) / status() 调用。

    注意：pywebview 会把公开属性都当成可调用接口扫描，所以内部状态一律用下划线开头。
    """

    def __init__(self) -> None:
        self._window = None
        self._session = ClaudeSession()
        self._busy = False
        self._lock = threading.Lock()
        self._tracker = AdjustmentTracker()
        self._lr = LrService()
        self._hub = ConfirmHub(self._emit, current_values=self._lr.current_values)
        self._hub.start()

    def _start_background(self) -> None:
        threading.Thread(target=self._lr.start, daemon=True).start()

    def _emit(self, ev: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onClaudeEvent && window.onClaudeEvent({json.dumps(ev, ensure_ascii=False)})")
        except Exception:
            pass  # 窗口已关闭

    def _on_event(self, ev: dict) -> None:
        """claude 的事件：先更新“本次调整”数据，再推给页面。"""
        with self._lock:
            changed = self._tracker.observe(ev)
            rows = self._tracker.snapshot() if changed else None
        self._emit(ev)
        if rows is not None:
            self._emit({"type": "adjust", "rows": rows})

    def _push_rows(self) -> None:
        with self._lock:
            rows = self._tracker.snapshot()
        self._emit({"type": "adjust", "rows": rows})

    def send(self, text: str, confirm: bool = True) -> dict:
        if self._busy:
            return {"ok": False, "message": "上一条请求仍在处理，请稍候。"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "message": "请输入内容。"}
        self._busy = True
        confirm = bool(confirm)
        self._tracker.confirm_on = confirm

        def run() -> None:
            token = self._hub.begin_turn()
            env = {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token}
            try:
                self._session.send(text, self._on_event, confirm=confirm, extra_env=env)
            except Exception as e:  # 兜底：不让后台线程悄悄死掉
                self._emit({"type": "error", "message": f"程序发生错误：{e}"})
                self._emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            finally:
                self._hub.end_turn()
                self._busy = False

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def stop(self) -> dict:
        self._hub.cancel_all()
        self._session.stop()
        return {"ok": True}

    def reset(self) -> dict:
        self._hub.cancel_all()
        self._session.reset()
        with self._lock:
            self._tracker.reset()
        self._push_rows()
        return {"ok": True}

    def answer(self, cid: str, allow: bool) -> dict:
        return {"ok": self._hub.answer(cid, bool(allow))}

    def status(self) -> dict:
        return {"connected": self._lr.connected}

    def undo(self, edit_id: str, force: bool = False) -> dict:
        r = self._lr.undo(edit_id, bool(force))
        if r["ok"]:
            with self._lock:
                self._tracker.mark_undone({edit_id})
            self._push_rows()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    def restore_original(self, force: bool = False) -> dict:
        r = self._lr.restore_original(bool(force))
        if r["ok"]:
            undone = set((r.get("result") or {}).get("edits_undone") or [])
            with self._lock:
                self._tracker.mark_undone(undone)
            self._push_rows()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}


def main() -> None:
    api = Api()
    api._window = webview.create_window(
        "修图助手",
        WEB.as_uri(),
        js_api=api,
        width=1440,
        height=860,
        min_size=(1100, 680),
        background_color="#17181b",
    )
    webview.start(api._start_background)


if __name__ == "__main__":
    main()
