"""PyInstaller 入口（LatosHue.exe / latoshue-helper.exe 共用）。

无参数：启动图形界面。子命令：--lr-launcher / --permission-server / --codex-proxy 是软件自己启动的辅助进程；
--selftest 不开窗口，只检查模块、资源、辅助进程、数据目录。开发时 `python app/main.py` 仍可直接运行。
"""
from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):                      # 开发时直接 python app/run_latoshue.py 也能跑
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))


def _gui() -> int:
    import main
    main.main()
    return 0


def _lr_launcher() -> int:
    import lr_launcher
    return lr_launcher.main()


def _permission_server() -> int:
    import permission_server
    permission_server.main()
    return 0


def _codex_proxy() -> int:
    import asyncio
    import codex_proxy
    asyncio.run(codex_proxy.main())
    return 0


def _selftest() -> int:
    import frozen
    return frozen.run_selftest()


COMMANDS = {
    "--lr-launcher": _lr_launcher,
    "--permission-server": _permission_server,
    "--codex-proxy": _codex_proxy,
    "--selftest": _selftest,
}


def run(argv: list[str], commands: dict | None = None, gui=None) -> int:
    table = COMMANDS if commands is None else commands
    if not argv:
        return (gui or _gui)()
    handler = table.get(argv[0])
    if handler is None or len(argv) > 1:
        if sys.stderr is not None:
            sys.stderr.write(f"未知参数：{' '.join(argv)}\n可用：{' '.join(table)}\n")
        return 2
    return handler()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(run(sys.argv[1:]))
