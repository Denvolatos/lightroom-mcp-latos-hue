"""打包（PyInstaller）感知：资源路径、辅助进程命令、自检。

开发时辅助进程是 `python <脚本>`；打包后没有 python，改成 `latoshue-helper.exe <子命令>`（与 LatosHue.exe 同目录）。
所有“怎么启动自己的辅助进程”都经过 helper_command，别处不要再拼 sys.executable。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
HELPER_EXE_NAME = "latoshue-helper.exe"
GUI_EXE_NAME = "LatosHue.exe"

# 辅助进程：名字 -> (开发时的脚本, 打包后的子命令)
HELPERS = {
    "lr-launcher": ("lr_launcher.py", "--lr-launcher"),
    "permission-server": ("permission_server.py", "--permission-server"),
    "codex-proxy": ("codex_proxy.py", "--codex-proxy"),
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """资源（web/）所在的根：打包后是 PyInstaller 解包目录（onedir 下的 _internal），开发时是 app/。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
    return APP_DIR


def web_dir() -> Path:
    return app_root() / "web"


def helper_exe() -> Path:
    return Path(sys.executable).resolve().parent / HELPER_EXE_NAME


def helper_command(name: str) -> list[str]:
    """启动辅助进程的命令行。"""
    if name not in HELPERS:
        raise KeyError(f"未知的辅助进程：{name}")
    script, flag = HELPERS[name]
    if is_frozen():
        return [str(helper_exe()), flag]
    return [sys.executable, str(APP_DIR / script)]


def selftest() -> tuple[bool, list[str]]:
    """不开窗口的自检：返回 (是否通过, 每项结果行)。"""
    lines: list[str] = []
    ok = True

    def check(label: str, fn) -> None:
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"OK   {label}" + (f"：{detail}" if detail else ""))
        except Exception as e:   # noqa: BLE001 - 自检要把任何缺失都报出来
            ok = False
            lines.append(f"FAIL {label}：{type(e).__name__}: {e}")

    def modules():
        import importlib
        names = ["adjustments", "backend", "claude_bridge", "codex_proxy", "confirm_hub", "export_service",
                 "import_service", "library_service", "lr_autostart", "lr_launcher", "lr_service", "main",
                 "permission_server", "persistent_session", "photo_library", "pick_apply", "pick_service",
                 "ports", "preview", "settings", "splash", "update_check", "wizard", "providers",
                 "providers.codex_provider", "webview"]
        for n in names:
            importlib.import_module(n)
        return f"{len(names)} 个模块"

    def resources():
        need = [web_dir() / "index.html", web_dir() / "assets" / "latos-hue-ribbon.ico",
                web_dir() / "assets" / "latos-hue-ribbon-192.png"]
        missing = [str(p) for p in need if not p.is_file()]
        if missing:
            raise FileNotFoundError("缺少 " + ", ".join(missing))

    def server_pkg():
        from lightroom_mcp import __version__
        from lightroom_mcp import bridge, edits, tools  # noqa: F401
        return f"lightroom_mcp {__version__}"

    def helpers():
        for n in HELPERS:
            cmd = helper_command(n)
            target = Path(cmd[0]) if is_frozen() else Path(cmd[1])
            if not target.is_file():
                raise FileNotFoundError(f"{n} -> {target}")
        return "冻结" if is_frozen() else "开发"

    def data_dir():
        from ports import STATE_DIR
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=STATE_DIR, prefix="selftest-", delete=True) as f:
            f.write(b"x")
        return str(STATE_DIR)

    check("导入模块", modules)
    check("资源文件", resources)
    check("server 包", server_pkg)
    check("辅助进程", helpers)
    check("数据目录可写", data_dir)
    return ok, lines


def run_selftest() -> int:
    """打印并返回退出码。窗口版 exe 没有控制台：结果同时写到 LATOSHUE_SELFTEST_OUT 指定的文件（默认临时目录）。"""
    ok, lines = selftest()
    text = "\n".join(lines) + "\n" + ("SELFTEST PASS" if ok else "SELFTEST FAIL") + \
        f" ({'frozen' if is_frozen() else 'dev'}, {Path(sys.executable).name})\n"
    out = os.environ.get("LATOSHUE_SELFTEST_OUT") or str(Path(tempfile.gettempdir()) / "latoshue_selftest.txt")
    try:
        Path(out).write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, ValueError, UnicodeError):
            pass
    return 0 if ok else 1
