"""由 claude 启动的 lightroom_mcp 服务入口（修图助手专用）。

与 `python -m lightroom_mcp` 的区别只有两点（server/ 的代码不动，这里只是换一个启动方式）：
1. 端口按“最久未使用”优先（见 ports.py），避免插件旧轮询任务拖慢新服务的发现；
2. 每秒把“插件是否已连上”写进一个小状态文件（环境变量 LRAPP_BRIDGE_STATE 指定路径，只含端口、是否连接、插件版本、时间），
   让窗口知道这条通道是否真的通了。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server"))

from ports import clean_stale_announcements, note_port_used, port_order  # noqa: E402


def write_state(path: Path, bridge, alive: bool = True, rpc_port: int | None = None) -> None:
    data = {"pid": os.getpid(), "port": bridge.port, "connected": bool(bridge.connected),
            "plugin_version": bridge.plugin_version, "t": time.time(), "alive": alive, "rpc_port": rpc_port}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def start_rpc(bridge, token: str):
    """窗口进程通过这个本机小接口借用本服务的插件通道（撤销、读取当前值、读取选中照片），
    这样整套系统只有一个 Bridge 服务——实测 Lightroom 插件同时轮询 3 个及以上服务时，其中一个会出现 5–10 秒延迟。
    只监听 127.0.0.1 随机端口，需要本次启动的一次性口令；命令名与参数格式沿用 Bridge.call 的校验。"""
    import hmac
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            got = self.headers.get("Authorization", "").encode("utf-8")
            if self.path != "/call" or not hmac.compare_digest(got, f"Bearer {token}".encode("utf-8")):
                return self._reply(401, {"ok": False, "error_type": "Unauthorized", "message": "未授权"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                data = bridge.call(str(body["command"]), body.get("params") or {}, float(body.get("timeout", 30)))
                self._reply(200, {"ok": True, "data": data})
            except Exception as e:   # 把服务端的异常类型名原样带回，窗口端据此翻成中文提示
                self._reply(200, {"ok": False, "error_type": type(e).__name__, "message": str(e)})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    from lightroom_mcp import config
    from lightroom_mcp.__main__ import _setup_logging
    from lightroom_mcp.bridge import Bridge, BridgeBusy
    from lightroom_mcp.tools import build_server
    from lightroom_mcp.update import UpdateChecker
    import logging

    _setup_logging()
    log = logging.getLogger("lrmcp")
    clean_stale_announcements()
    bridge, busy = Bridge(ports=port_order()), None
    try:
        bridge.start()
        note_port_used(bridge.port)
        log.info("bridge (app launcher) listening on %s:%s", config.HOST, bridge.port)
    except BridgeBusy as e:
        bridge, busy = None, str(e)
        log.warning("%s", busy)
    state_path = os.environ.get("LRAPP_BRIDGE_STATE")
    rpc = start_rpc(bridge, os.environ["LRAPP_RPC_TOKEN"]) if bridge is not None and os.environ.get("LRAPP_RPC_TOKEN") else None
    rpc_port = rpc.server_address[1] if rpc else None
    stop = threading.Event()
    if bridge is not None and state_path:
        sp = Path(state_path)
        sp.parent.mkdir(parents=True, exist_ok=True)

        def loop() -> None:
            while not stop.is_set():
                write_state(sp, bridge, rpc_port=rpc_port)
                stop.wait(1.0)
        threading.Thread(target=loop, daemon=True).start()
    updates = UpdateChecker()
    updates.start_in_background()
    try:
        build_server(bridge, busy, updates).run()   # stdio
    finally:
        stop.set()
        if bridge is not None:
            bridge.stop()
        if state_path:
            try:
                Path(state_path).unlink(missing_ok=True)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
