"""启动界面（0.13.0）：软件打开到主界面之前显示的小窗口（圆角深色底 + 丝带图标 + 名称 + 版本号 + 一行进度文字）。

实现方式：pywebview 的无边框小窗口，内容是一段内嵌的 HTML（图标用 data 地址，不读其他文件，出现得最快）；
主窗口先隐藏着加载，主界面准备好（页面调用 ui_ready）后显示主窗口并关闭启动窗口。
安全底线：启动界面绝不能卡住软件——
- 任何一步出错都只当作"没有启动界面"，直接显示主窗口；
- 看门狗计时器：到点（默认 20 秒）无论主界面是否报告准备好，都显示主窗口并关闭启动窗口；
- 窗口调用都放在后台线程里做（pywebview 的窗口调用在页面没加载好时会阻塞等待），主流程不会被它拖住。
所有窗口对象都是注入的，测试里只用假对象，不会弹出任何窗口。
"""
from __future__ import annotations

import base64
import html as _html
import json
import queue
import threading
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "web" / "assets"
ICON_PNG = ASSETS / "latos-hue-ribbon-192.png"
ICON_ICO = ASSETS / "latos-hue-ribbon.ico"
WIDTH, HEIGHT = 460, 280
TITLE = "Latos Hue 修图助手"
WATCHDOG_SECONDS = 20.0
CORNER = 32                          # 圆角直径（像素）

# 进度文字（大白话）
TEXT_CHECK = "正在检查环境…"
TEXT_SERVICES = "正在启动后台服务…"
TEXT_LOADING = "正在载入界面…"
TEXT_LAUNCH_LR = "正在启动 Lightroom…"
TEXT_CONNECT_LR = "正在连接 Lightroom…"


def icon_data_uri(path: Path = ICON_PNG) -> str:
    """把图标读成 data 地址；读不到就返回空串（启动界面照样能显示，只是没有图标）。"""
    try:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return ""


def splash_html(version: str, text: str = TEXT_CHECK, icon_uri: str | None = None) -> str:
    icon = icon_data_uri() if icon_uri is None else icon_uri
    img = f'<img class="ic" src="{icon}" alt="">' if icon else '<div class="ic"></div>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{_html.escape(TITLE)}</title><style>
html,body{{margin:0;height:100%;background:#17181b;overflow:hidden;font-family:"Segoe UI","Microsoft YaHei UI",sans-serif;color:#e6e7ea;user-select:none;cursor:default}}
.card{{box-sizing:border-box;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;background:linear-gradient(160deg,#1d1f24,#141518);border:1px solid #2b2d33;border-radius:{CORNER // 2}px}}
.ic{{width:96px;height:96px;object-fit:contain;margin-bottom:6px}}
.name{{font-size:22px;font-weight:600;letter-spacing:.5px}}
.ver{{font-size:12px;color:#8b8f99}}
.msg{{margin-top:18px;font-size:13px;color:#a9adb7;min-height:18px}}
.bar{{margin-top:8px;width:180px;height:3px;border-radius:2px;background:#2a2c32;overflow:hidden;position:relative}}
.bar i{{position:absolute;top:0;left:-40%;width:40%;height:100%;border-radius:2px;background:#4f8cff;animation:go 1.3s ease-in-out infinite}}
@keyframes go{{0%{{left:-40%}}100%{{left:100%}}}}
</style></head><body><div class="card">{img}<div class="name">Latos Hue 修图助手</div><div class="ver">版本 {_html.escape(version)}</div>
<div class="msg" id="msg">{_html.escape(text)}</div><div class="bar"><i></i></div></div>
<script>function setText(t){{document.getElementById('msg').textContent=t;}}</script></body></html>"""


def round_corners(window, size: tuple[int, int] = (WIDTH, HEIGHT)) -> bool:
    """尽力而为：给无边框的启动窗口裁出圆角（Windows 的 SetWindowRgn）。任何失败都忽略（窗口仍是方角深色，照常使用）。"""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(window.native.Handle.ToInt32())
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        w, h = rect.right - rect.left, rect.bottom - rect.top
        scale = max(1.0, w / float(size[0]))
        r = int(CORNER * scale)
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        return bool(ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True))
    except Exception:                                  # noqa: BLE001
        return False


class SplashController:
    """管理启动窗口与主窗口的交接。splash 或 main 可以为 None（创建启动窗口失败时）：此时 finish() 只负责显示主窗口。"""

    def __init__(self, splash, main, *, watchdog: float = WATCHDOG_SECONDS, timer_factory=threading.Timer):
        self.splash, self.main = splash, main
        self._done = False
        self._lock = threading.Lock()
        self._q: queue.Queue = queue.Queue()
        self._last_text = ""
        self._handover: threading.Thread | None = None   # 交接线程（测试用它等待完成）
        self._timer = timer_factory(watchdog, self.finish)
        if hasattr(self._timer, "daemon"):
            self._timer.daemon = True
        self._worker = threading.Thread(target=self._work, daemon=True)

    @property
    def done(self) -> bool:
        return self._done

    def start(self) -> None:
        self._timer.start()
        self._worker.start()

    # ---- 进度文字 --------------------------------------------------
    def set_text(self, text: str) -> None:
        """更新启动界面的一行文字。只排队，不阻塞调用者；已结束则忽略。"""
        if self._done or self.splash is None:
            return
        self._q.put(text)

    def _work(self) -> None:
        while True:
            text = self._q.get()
            if text is None or self._done:
                return
            self._last_text = text
            try:
                self.splash.evaluate_js(f"setText({json.dumps(text, ensure_ascii=False)})")
            except Exception:                          # noqa: BLE001 - 窗口还没好或已关闭：不影响主流程
                pass

    # ---- 交接 ------------------------------------------------------
    def finish(self) -> bool:
        """显示主窗口并关闭启动窗口。只执行一次（页面准备好、看门狗到点、主窗口被关闭都可能触发）。返回本次是否真正执行。"""
        with self._lock:
            if self._done:
                return False
            self._done = True
        try:
            self._timer.cancel()
        except Exception:                              # noqa: BLE001
            pass
        self._q.put(None)

        def handover() -> None:
            if self.main is not None:
                try:
                    self.main.show()
                except Exception:                      # noqa: BLE001 - 显示失败也要继续关闭启动窗口
                    pass
            if self.splash is not None:
                try:
                    self.splash.destroy()
                except Exception:                      # noqa: BLE001
                    pass
        self._handover = threading.Thread(target=handover, daemon=True)
        self._handover.start()
        return True
