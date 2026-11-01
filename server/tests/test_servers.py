"""Several lrmcp servers at once (0.3.0): each takes the first free port and announces itself to the plug-in."""
import socket

import pytest

from lightroom_mcp import config
from lightroom_mcp.bridge import Bridge, BridgeBusy


def free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return sorted(s.getsockname()[1] for s in socks)
    finally:
        for s in socks:
            s.close()


def test_each_server_takes_the_next_free_port_and_announces_itself(tmp_path):
    ports = free_ports(3)
    servers = [Bridge(ports=ports, data_dir=tmp_path, poll_hold=0.2) for _ in range(3)]
    try:
        for b in servers:
            b.start()
        assert sorted(b.port for b in servers) == ports
        assert len({b.token for b in servers}) == 3  # every server has its own token
        files = sorted(p.stem for p in (tmp_path / "servers").glob("*.txt"))
        assert files == sorted(str(p) for p in ports)
        for b in servers:
            text = (tmp_path / "servers" / f"{b.port}.txt").read_text()
            assert f"port={b.port}" in text and f"token={b.token}" in text
    finally:
        for b in servers:
            b.stop()
    assert not list((tmp_path / "servers").glob("*.txt"))  # everybody cleaned up


def test_a_server_stopping_does_not_affect_the_others(tmp_path):
    # both use the same candidate list so they must end up on different ports
    ports = free_ports(2)
    a, b = Bridge(ports=ports, data_dir=tmp_path), Bridge(ports=ports, data_dir=tmp_path)
    a.start()
    b.start()
    try:
        assert a.port != b.port
        a.stop()
        assert (tmp_path / "servers" / f"{b.port}.txt").exists()
        assert not (tmp_path / "servers" / f"{a.port}.txt").exists()
        assert b.other_servers() == []
    finally:
        b.stop()


def test_other_servers_lists_the_other_sessions(tmp_path):
    ports = free_ports(2)
    a, b = Bridge(ports=ports, data_dir=tmp_path), Bridge(ports=ports, data_dir=tmp_path)
    a.start()
    b.start()
    try:
        assert a.other_servers() == [b.port] and b.other_servers() == [a.port]
    finally:
        a.stop()
        b.stop()


def test_range_exhausted_gives_a_clear_message(tmp_path):
    ports = free_ports(2)
    held = [Bridge(ports=ports, data_dir=tmp_path) for _ in range(2)]
    for b in held:
        b.start()
    try:
        with pytest.raises(BridgeBusy) as err:
            Bridge(ports=ports, data_dir=tmp_path).start()
        assert "都被占用" in str(err.value) and "2 个" in str(err.value)
    finally:
        for b in held:
            b.stop()


def test_announcements_of_dead_servers_are_cleaned_up_at_start(tmp_path):
    dead_port = free_ports(1)[0]  # nothing listens there
    (tmp_path / "servers").mkdir()
    stale = tmp_path / "servers" / f"{dead_port}.txt"
    stale.write_text(f"port={dead_port}\ntoken=x\npid=1\n")
    (tmp_path / "servers" / "notes.txt").write_text("not a server")  # unrelated file: untouched
    b = Bridge(ports=free_ports(1), data_dir=tmp_path)
    b.start()
    try:
        assert not stale.exists()
        assert (tmp_path / "servers" / "notes.txt").exists()
    finally:
        b.stop()


def test_a_live_servers_announcement_is_not_removed(tmp_path):
    ports = free_ports(2)
    a, b = Bridge(ports=ports, data_dir=tmp_path), Bridge(ports=ports, data_dir=tmp_path)
    a.start()
    b.start()  # b's start-up cleanup must leave a's announcement alone
    try:
        assert (tmp_path / "servers" / f"{a.port}.txt").exists()
    finally:
        a.stop()
        b.stop()


def test_default_range_starts_at_the_legacy_port():
    b = Bridge(data_dir=config.DATA_DIR)  # not started: only look at the candidates
    assert b.candidates[0] == config.PORT == 58770
    assert len(b.candidates) == config.PORT_COUNT == 20
