"""修图助手（模板）：只打开界面，不连接 Lightroom，也不连接 AI。

运行：python app/main.py
"""
from pathlib import Path

import webview

WEB = Path(__file__).resolve().parent / "web" / "index.html"


def main() -> None:
    webview.create_window(
        "修图助手（模板）",
        WEB.as_uri(),
        width=1440,
        height=860,
        min_size=(1100, 680),
        background_color="#17181b",
    )
    webview.start()


if __name__ == "__main__":
    main()
