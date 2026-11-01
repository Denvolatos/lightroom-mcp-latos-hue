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


def serve() -> int:
    from .tools import build_server

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
    try:
        build_server(bridge, busy).run()  # stdio
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
    if args[:1] in ([], ["serve"]):
        return serve()
    print("用法：lrmcp [serve] | doctor | --version", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
