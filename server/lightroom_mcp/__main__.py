# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Entry point: ``lrmcp`` (MCP server over stdio), ``lrmcp doctor``, ``lrmcp --version``."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import __version__, config
from .bridge import Bridge, BridgeBusy


def _setup_logging() -> None:
    """stdout belongs to the MCP protocol, so log to a file only."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config.LOG_FILE, maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


_ASCII_MARKS = {"✅": "[OK]", "❌": "[X]", "➖": "[-]", "ℹ️": "[i]", "→": "->"}


def out(text: str, stream=None) -> None:
    """Print for the command line. A Chinese Windows console is GBK and cannot encode the check marks
    (printing them crashed the program), so fall back to plain markers instead of failing."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        for mark, plain in _ASCII_MARKS.items():
            text = text.replace(mark, plain)
        text = text.encode(encoding, errors="replace").decode(encoding)
    print(text, file=stream)


def serve() -> int:
    from .tools import build_server
    from .update import UpdateChecker

    _setup_logging()
    log = logging.getLogger("lrmcp")
    bridge: Bridge | None = Bridge()
    busy: str | None = None
    try:
        bridge.start()
        log.info("bridge listening on %s:%s", config.HOST, config.PORT)
    except BridgeBusy as e:
        bridge, busy = None, str(e)
        log.warning("%s", busy)
    updates = UpdateChecker()
    updates.start_in_background()
    try:
        build_server(bridge, busy, updates).run()  # stdio
    finally:
        if bridge is not None:
            bridge.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["--version"], ["-V"]):
        print(f"lightroom_mcp {__version__}")
        return 0
    if args[:1] == ["doctor"]:
        from . import doctor

        return doctor.main(args[1:])
    if args[:1] in (["register"], ["unregister"]):
        from . import register

        fn = register.register if args[0] == "register" else register.unregister
        out("\n".join(fn(dry_run="--dry-run" in args[1:])))
        return 0
    if args[:1] in ([], ["serve"]):
        return serve()
    print("用法：lrmcp [serve] | doctor | register [--dry-run] | unregister [--dry-run] | --version", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
