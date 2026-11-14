# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import json
import os
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


def test_announcement_file_written_and_removed(tmp_path):
    port = free_port()
    b = Bridge(port=port, data_dir=tmp_path)
    b.start()
    info = dict(line.split("=", 1) for line in (tmp_path / "servers" / f"{port}.txt").read_text().split())
    assert info["port"] == str(port) and info["token"] == b.token and info["pid"] == str(os.getpid())
    assert not (tmp_path / "token").exists()  # the legacy token file belongs to the server on the legacy port only
    b.stop()
    assert not (tmp_path / "servers" / f"{port}.txt").exists()


def test_the_server_on_the_legacy_port_also_writes_the_old_token_file(tmp_path):
    port = free_port()
    b = Bridge(port=port, data_dir=tmp_path, legacy_port=port)
    b.start()
    assert (tmp_path / "token").read_text() == b.token  # an old 0.2.x plug-in reads this
    b.stop()
    assert not (tmp_path / "token").exists()


def test_no_free_port_is_refused_with_chinese_message(bridge, tmp_path):
    other = Bridge(port=bridge.port, data_dir=tmp_path / "other")  # the only candidate is taken
    with pytest.raises(BridgeBusy) as err:
        other.start()
    assert "都被占用" in str(err.value)
    assert not list((tmp_path / "other" / "servers").glob("*.txt"))  # nothing announced


def test_port_can_be_reused_right_after_stop(tmp_path):
    port = free_port()
    first = Bridge(port=port, data_dir=tmp_path, poll_hold=0.2)
    first.start()
    request(first, "GET", "/poll", headers={"X-Gen": "1"})  # leave a finished connection behind
    first.stop()
    second = Bridge(port=port, data_dir=tmp_path)
    second.start()  # must not raise
    second.stop()


def test_deleted_announcement_is_written_back(bridge, tmp_path):
    info = tmp_path / "servers" / f"{bridge.port}.txt"
    info.unlink()
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1] == "none"
    assert f"token={bridge.token}" in info.read_text()  # same token, so the running plug-in keeps working


def test_deleted_legacy_token_file_is_written_back(tmp_path):
    port = free_port()
    b = Bridge(port=port, data_dir=tmp_path, poll_hold=0.2, legacy_port=port)
    b.start()
    try:
        (tmp_path / "token").unlink()
        assert request(b, "GET", "/poll", headers={"X-Gen": "1"})[1] == "none"
        assert (tmp_path / "token").read_text() == b.token
    finally:
        b.stop()


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


def test_poll_skips_command_after_caller_times_out(bridge):
    bridge.last_seen = time.time()
    with pytest.raises(BridgeError, match="没有在"):
        bridge.call("status", timeout=0.1)
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1] == "none"


def test_bad_parameters_are_rejected(bridge):
    bridge.last_seen = time.time()
    with pytest.raises(ValueError):
        bridge.call("status", {"photo": "a b"})
    with pytest.raises(ValueError):
        bridge.call("status", {"bad key": "x"})


def test_old_plugin_instance_is_told_to_stop(bridge):
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "200"})[1] == "none"
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "100"})[1] == "stop"


# ---- 0.14: stop() wakes every waiting /poll at once ---------------------------------------------------
def test_stop_wakes_a_hanging_poll_immediately(tmp_path):
    b = Bridge(port=free_port(), data_dir=tmp_path, poll_hold=10, connect_wait=0)
    b.start()
    answers = []

    def poll():
        answers.append(request(b, "GET", "/poll", headers={"X-Gen": "1"}))

    threads = [threading.Thread(target=poll) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.5)  # both polls are now waiting for a job
    started = time.monotonic()
    b.stop()
    for t in threads:
        t.join(5)
    elapsed = time.monotonic() - started
    assert elapsed < 2, f"stop() and the woken polls took {elapsed:.1f} s"
    assert answers == [(200, "none"), (200, "none")]


def test_stop_removes_the_announcement_before_the_port_is_free(tmp_path):
    b = Bridge(port=free_port(), data_dir=tmp_path, poll_hold=10, connect_wait=0, legacy_port=None)
    b.start()
    info = b.info_file
    assert info.exists()
    b.stop()
    assert not info.exists()
    b.stop()  # a second stop is harmless


def test_new_server_on_the_same_port_right_after_stop_gets_its_own_token(tmp_path):
    port = free_port()
    old = Bridge(port=port, data_dir=tmp_path, poll_hold=10, connect_wait=0)
    old.start()
    waiter = threading.Thread(target=lambda: request(old, "GET", "/poll", headers={"X-Gen": "1"}))
    waiter.start()
    time.sleep(0.3)
    old.stop()
    new = Bridge(port=port, data_dir=tmp_path, poll_hold=0.3, connect_wait=0)
    new.start()
    try:
        waiter.join(3)
        assert not waiter.is_alive()
        assert new.token != old.token
        assert f"token={new.token}" in new.info_file.read_text()
        assert request(old, "GET", "/poll", headers={"X-Gen": "1"})[0] == 401  # the old token no longer works
    finally:
        new.stop()


# ---- 1.1.1: a command the plug-in is still working on counts as connected --------------------------------------------
def test_plugin_running_a_long_command_stays_connected(bridge, monkeypatch):
    from lightroom_mcp import config

    monkeypatch.setattr(config, "PLUGIN_SEEN_SECONDS", 0.5)   # 25 s in real life; a long export takes minutes
    release = threading.Event()

    def slow(cmd, params):
        release.wait(5)
        return {"ok": True, "data": {"cmd": cmd}}

    stop = fake_plugin(bridge, slow)
    try:
        assert bridge.wait_connected(3)
        result = []
        caller = threading.Thread(target=lambda: result.append(bridge.call("export_photo", timeout=10)))
        caller.start()
        time.sleep(1.2)                       # no /poll for more than PLUGIN_SEEN_SECONDS: the plug-in is busy
        assert bridge.executing and bridge.connected
        release.set()
        caller.join(5)
        assert result == [{"cmd": "export_photo"}] and not bridge.executing
    finally:
        stop.set()


def test_a_taken_command_whose_caller_gave_up_no_longer_counts(bridge, monkeypatch):
    from lightroom_mcp import config

    monkeypatch.setattr(config, "PLUGIN_SEEN_SECONDS", 0.2)
    bridge.last_seen = time.time()
    caller = threading.Thread(target=lambda: pytest.raises(BridgeError, bridge.call, "export_photo", timeout=0.8))
    caller.start()
    time.sleep(0.1)
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1].startswith("cmd ")   # taken, never answered
    time.sleep(0.4)
    assert bridge.connected                   # still working on it
    caller.join(3)
    time.sleep(0.25)
    assert not bridge.executing and not bridge.connected


# ---- 1.1.1: stop() wakes waiting calls; "never taken" is told apart from "taken, no answer"; no stale results ---------
def test_a_command_still_queued_at_the_timeout_is_not_run(bridge):
    from lightroom_mcp.bridge import BridgeNotRun, BridgeTimeout

    bridge.last_seen = time.time()
    with pytest.raises(BridgeNotRun, match="没有执行") as err:
        bridge.call("set_develop", timeout=0.3)
    assert not isinstance(err.value, BridgeTimeout)       # certain: nothing was done, safe to retry
    assert request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1] == "none"   # and the plug-in never gets it


def test_a_taken_command_without_answer_is_a_timeout_and_its_late_result_is_dropped(bridge):
    from lightroom_mcp.bridge import BridgeNotRun, BridgeTimeout

    bridge.last_seen = time.time()
    lines = []
    poller = threading.Thread(target=lambda: lines.append(request(bridge, "GET", "/poll", headers={"X-Gen": "1"})[1]))
    poller.start()
    with pytest.raises(BridgeTimeout) as err:
        bridge.call("set_develop", timeout=0.6)
    assert not isinstance(err.value, BridgeNotRun)
    poller.join(3)
    job_id = lines[0].split(" ")[1]
    assert request(bridge, "POST", f"/result?id={job_id}", json.dumps({"ok": True, "data": {}}))[0] == 200
    assert bridge._results == {} and bridge._events == {} and bridge._inflight == {}


def test_stop_wakes_waiting_calls_at_once(tmp_path):
    from lightroom_mcp.bridge import BridgeNotRun, BridgeTimeout

    b = Bridge(port=free_port(), data_dir=tmp_path, poll_hold=0.3, connect_wait=0)
    b.start()
    b.last_seen = time.time()
    errors = {}

    def call(name):
        try:
            b.call(name, timeout=60)
        except Exception as e:  # noqa: BLE001
            errors[name] = e

    taken = threading.Thread(target=call, args=("export_photo",))
    taken.start()
    time.sleep(0.1)
    assert request(b, "GET", "/poll", headers={"X-Gen": "1"})[1].startswith("cmd ")   # the plug-in took the export
    queued = threading.Thread(target=call, args=("get_preview",))
    queued.start()
    time.sleep(0.1)
    started = time.monotonic()
    b.stop()
    taken.join(3)
    queued.join(3)
    assert time.monotonic() - started < 2
    assert type(errors["export_photo"]) is BridgeTimeout and "不确定" in str(errors["export_photo"])
    assert type(errors["get_preview"]) is BridgeNotRun
    with pytest.raises(BridgeNotRun):
        b.call("status", timeout=1)
