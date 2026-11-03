"""修图助手：打开界面，对话框接到本机已登录的 Claude Code 命令行（只读阶段，不改照片）。

运行：python app/main.py
"""
import json
import sys
import threading
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_bridge import ClaudeSession  # noqa: E402

WEB = Path(__file__).resolve().parent / "web" / "index.html"


class Api:
    """页面里用 window.pywebview.api.send(text) / stop() / reset() 调用。

    注意：pywebview 会把公开属性都当成可调用接口扫描，所以内部状态一律用下划线开头。
    """

    def __init__(self) -> None:
        self._window = None
        self._session = ClaudeSession()
        self._busy = False

    def _emit(self, ev: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onClaudeEvent && window.onClaudeEvent({json.dumps(ev, ensure_ascii=False)})")
        except Exception:
            pass  # 窗口已关闭

    def send(self, text: str) -> dict:
        if self._busy:
            return {"ok": False, "message": "上一句还在处理中，请稍等。"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "message": "请先输入内容。"}
        self._busy = True

        def run() -> None:
            try:
                self._session.send(text, self._emit)
            except Exception as e:  # 兜底：不让后台线程悄悄死掉
                self._emit({"type": "error", "message": f"程序出错了：{e}"})
                self._emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            finally:
                self._busy = False

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def stop(self) -> dict:
        self._session.stop()
        return {"ok": True}

    def reset(self) -> dict:
        self._session.reset()
        return {"ok": True}


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
    webview.start()


if __name__ == "__main__":
    main()
