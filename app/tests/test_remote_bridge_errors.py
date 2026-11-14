# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""借用通道（RemoteBridge）的网络错误分类（1.1.1）：只有“连接被拒绝 / 没有端口 / 服务以错误码拒绝”才算没连上；
请求发出之后的中断（连接重置、回包残缺、读超时）一律算“结果不确定”（BridgeTimeout），修改记录才能被还原。"""
import json
import socket
import threading
import time

import pytest

from lr_service import LrService, RemoteBridge, _import_server

_, bridge_mod = _import_server()


def state(tmp_path, port):
    p = tmp_path / "side.json"
    p.write_text(json.dumps({"t": time.time(), "connected": True, "rpc_port": port}), encoding="utf-8")
    return p


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RawServer:
    """读完请求后按 mode 回应：drop = 不回任何字节直接断开；garbage = 回一段不完整的 HTTP 响应。"""

    def __init__(self, mode):
        self.mode, self.got = mode, threading.Event()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            c, _ = self.sock.accept()
        except OSError:
            return
        c.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
        self.got.set()                       # 请求已送达
        if self.mode == "garbage":
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{\"ok\": tr")
        c.close()

    def close(self):
        self.sock.close()


def test_refused_connection_is_not_connected(tmp_path):
    rb = RemoteBridge(state(tmp_path, free_port()), "tok")
    with pytest.raises(bridge_mod.PluginNotConnected):
        rb.call("set_develop", {}, timeout=1)


def test_missing_port_is_not_connected(tmp_path):
    p = tmp_path / "side.json"
    p.write_text(json.dumps({"t": time.time(), "connected": True}), encoding="utf-8")
    with pytest.raises(bridge_mod.PluginNotConnected):
        RemoteBridge(p, "tok").call("set_develop", {}, timeout=1)


@pytest.mark.parametrize("mode", ["drop", "garbage"])
def test_break_after_request_sent_is_uncertain(tmp_path, mode):
    srv = RawServer(mode)
    try:
        rb = RemoteBridge(state(tmp_path, srv.port), "tok")
        with pytest.raises(bridge_mod.BridgeTimeout):
            rb.call("set_develop", {"photo": "P1"}, timeout=1)
        assert srv.got.is_set()
    finally:
        srv.close()


def test_http_error_reply_is_not_connected(tmp_path):
    import lr_launcher

    class B:
        def call(self, *a, **k):
            return {}
    srv = lr_launcher.start_rpc(B(), "right")
    try:
        rb = RemoteBridge(state(tmp_path, srv.server_address[1]), "wrong")
        with pytest.raises(bridge_mod.PluginNotConnected):     # 服务以 401 拒绝：命令没有执行
            rb.call("set_develop", {}, timeout=1)
    finally:
        srv.shutdown()


def test_uncertain_write_through_edit_service_can_be_restored(tmp_path):
    """写入发出后连接断开：LrService 报“待确认”，不是“未连接”。"""
    srv = RawServer("drop")
    try:
        lr = LrService(bridge=RemoteBridge(state(tmp_path, srv.port), "tok"), edit_service=None)

        class Svc:
            def restore(self, *a):
                return lr._bridge.call("restore", {}, timeout=1)
        lr._edits = Svc()
        r = lr.undo("20261114-120000-ab12")
        assert r["ok"] is False and r["uncertain"] is True and "待确认" in r["message"]
    finally:
        srv.close()
