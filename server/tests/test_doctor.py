import socket

from lightroom_mcp import doctor
from lightroom_mcp.bridge import Bridge


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def test_lightroom_not_running_is_diagnosed(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: False)
    b = Bridge(port=free_port(), data_dir=tmp_path, connect_wait=0)
    b.start()
    try:
        c = by_name(doctor.run_checks(b), "Lightroom 是否在运行")
    finally:
        b.stop()
    assert not c.ok and "打开 Lightroom" in c.fix


def test_plugin_not_loaded_is_diagnosed(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    b = Bridge(port=free_port(), data_dir=tmp_path, connect_wait=0)
    b.start()
    try:
        checks = doctor.run_checks(b)
    finally:
        b.stop()
    assert by_name(checks, "Lightroom 是否在运行").ok
    plugin = by_name(checks, "Lightroom 插件已连上")
    assert not plugin.ok and "增效工具管理器" in plugin.fix


def test_plugin_connected_is_reported_with_version(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    b = Bridge(port=free_port(), data_dir=tmp_path, connect_wait=0)
    b.start()
    try:
        import time

        b.last_seen = time.time()
        b.plugin_version = "9.9.9"
        plugin = by_name(doctor.run_checks(b), "Lightroom 插件已连上")
    finally:
        b.stop()
    assert plugin.ok and "9.9.9" in plugin.detail


def test_busy_port_is_diagnosed(monkeypatch):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    checks = doctor.run_checks(None, "端口 58770 已被占用")
    port = by_name(checks, "本机通信端口")
    assert not port.ok and "已被占用" in port.detail


def test_report_counts_problems(monkeypatch):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: False)
    text = doctor.format_report(doctor.run_checks(None, "端口被占用"))
    assert "❌" in text and "需要处理" in text
