import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from lightroom_mcp.bridge import Bridge, BridgeBusy, BridgeError, PluginNotConnected


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def bridge(tmp_path):
    b = Bridge(port=free_port(), data_dir=tmp_path, poll_hold=0.3, connect_wait=0)
    b.start()
    yield b
    b.stop()


def request(b, method, path, body=None, token=None, headers=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{b.port}{path}",
        data=body.encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {token if token is not None else b.token}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def fake_plugin(b, handler, gen="100"):
    """Poll like the Lua plug-in does and answer each ``cmd`` line with handler(command, params)."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            status, body = request(b, "GET", "/poll", headers={"X-Gen": gen})
            if status != 200 or body in ("none", "stop"):
                if body == "stop":
                    return
                continue
            _, job_id, command, *kv = body.split(" ")
            params = dict(item.split("=", 1) for item in kv)
            request(b, "POST", f"/result?id={job_id}", json.dumps(handler(command, params)))

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return stop


def test_token_file_written_and_removed(tmp_path):
    b = Bridge(port=free_port(), data_dir=tmp_path)
    b.start()
    assert (tmp_path / "token").read_text() == b.token
    b.stop()
    assert not (tmp_path / "token").exists()


def test_second_instance_is_refused_with_chinese_message(bridge, tmp_path):
    other = Bridge(port=bridge.port, data_dir=tmp_path / "other")
    with pytest.raises(BridgeBusy) as err:
        other.start()
    assert "已被占用" in str(err.value)
    assert not (tmp_path / "other" / "token").exists()  # must not overwrite the running instance's token


def test_port_can_be_reused_right_after_stop(tmp_path):
    port = free_port()
    first = Bridge(port=port, data_dir=tmp_path, poll_hold=0.2)
    first.start()
    request(first, "GET", "/poll", headers={"X-Gen": "1"})  # leave a finished connection behind
    first.stop()
    second = Bridge(port=port, data_dir=tmp_path)
    second.start()  # must not raise
    second.stop()


def test_deleted_token_file_is_written_back(bridge, tmp_path):
    token_file = tmp_path / "token"
    token_file.unlink()
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1] == "none"
    assert token_file.read_text() == bridge.token  # same token, so the running plug-in keeps working


def test_wrong_token_is_401(bridge):
    assert request(bridge, "GET", "/poll", token="nope")[0] == 401


def test_origin_header_is_refused(bridge):
    assert request(bridge, "GET", "/poll", headers={"Origin": "http://evil.example"})[0] == 403


def test_wrong_host_is_refused(bridge):
    assert request(bridge, "GET", "/poll", headers={"Host": "evil.example"})[0] == 400


def test_call_without_plugin_raises(bridge):
    with pytest.raises(PluginNotConnected):
        bridge.call("status")


def test_round_trip(bridge):
    stop = fake_plugin(bridge, lambda cmd, params: {"ok": True, "data": {"cmd": cmd, "params": params}})
    try:
        assert bridge.wait_connected(3)
        data = bridge.call("get_preview", {"photo": "selected", "long_edge": 1024}, timeout=5)
        assert data == {"cmd": "get_preview", "params": {"photo": "selected", "long_edge": "1024"}}
    finally:
        stop.set()


def test_call_waits_for_a_plugin_that_is_still_connecting(tmp_path):
    b = Bridge(port=free_port(), data_dir=tmp_path, poll_hold=0.3, connect_wait=3)
    b.start()
    try:
        started = []

        def late():
            time.sleep(0.5)
            started.append(fake_plugin(b, lambda cmd, params: {"ok": True, "data": {"cmd": cmd}}))

        threading.Thread(target=late, daemon=True).start()
        assert b.call("status", timeout=5) == {"cmd": "status"}
        for stop in started:
            stop.set()
    finally:
        b.stop()


def test_plugin_error_becomes_bridge_error(bridge):
    stop = fake_plugin(bridge, lambda cmd, params: {"ok": False, "error": "没有选中照片"})
    try:
        assert bridge.wait_connected(3)
        with pytest.raises(BridgeError, match="没有选中照片"):
            bridge.call("list_selected", timeout=5)
    finally:
        stop.set()


def test_timeout_raises(bridge):
    bridge.last_seen = time.time()  # pretend the plug-in is there but never answers
    with pytest.raises(BridgeError, match="没有在"):
        bridge.call("status", timeout=0.5)


def test_bad_parameters_are_rejected(bridge):
    bridge.last_seen = time.time()
    with pytest.raises(ValueError):
        bridge.call("status", {"photo": "a b"})
    with pytest.raises(ValueError):
        bridge.call("status", {"bad key": "x"})


def test_old_plugin_instance_is_told_to_stop(bridge):
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "200"})[1] == "none"
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "100"})[1] == "stop"
