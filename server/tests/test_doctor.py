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
        plugin = by_name(doctor.run_checks(b, probe=False), "Lightroom 插件已连上")
    finally:
        b.stop()
    assert plugin.ok and "9.9.9" in plugin.detail


def test_other_ai_sessions_are_mentioned(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    ports = [free_port(), free_port()]
    a, b = Bridge(ports=ports, data_dir=tmp_path), Bridge(ports=ports, data_dir=tmp_path)
    a.start()
    b.start()
    try:
        detail = by_name(doctor.run_checks(a, probe=False), "本机通信端口").detail
    finally:
        a.stop()
        b.stop()
    assert "另有 1 个 AI 会话" in detail and str(b.port) in detail


def test_untested_lightroom_version_is_said_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    b = Bridge(port=free_port(), data_dir=tmp_path, connect_wait=0)
    b.start()
    try:
        import time

        b.last_seen = time.time()
        b.call = lambda command, params=None, timeout=30.0: {"lightroom_version": "13.4.0"}
        check = doctor._lightroom_version_check(b)
        b.call = lambda command, params=None, timeout=30.0: {"lightroom_version": "15.2.0"}
        tested = doctor._lightroom_version_check(b)
    finally:
        b.stop()
    assert check.ok and "只在 15.2 上测试过" in check.detail and "兼容性报告" in check.detail
    assert tested.ok and "测试过" in tested.detail and "没有验证" not in tested.detail


def test_busy_port_is_diagnosed(monkeypatch):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: True)
    checks = doctor.run_checks(None, "端口 58770 已被占用")
    port = by_name(checks, "本机通信端口")
    assert not port.ok and "已被占用" in port.detail


def test_report_counts_problems(monkeypatch):
    monkeypatch.setattr(doctor, "_lightroom_running", lambda: False)
    text = doctor.format_report(doctor.run_checks(None, "端口被占用"))
    assert "❌" in text and "需要处理" in text


class _Completed:
    def __init__(self, stdout):
        self.stdout = stdout


def test_mac_process_list_is_read_with_ps(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Completed("/usr/sbin/cfprefsd\n/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app/Contents/MacOS/Adobe Lightroom Classic\n")

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor._lightroom_running() is True
    assert seen["cmd"][0] == "ps"
    assert doctor._lightroom_process_label() == "Adobe Lightroom Classic"


def test_mac_other_apps_do_not_count_as_lightroom(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.subprocess, "run", lambda cmd, **kw: _Completed("/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app/Contents/MacOS/Adobe Photoshop 2026\n"))
    assert doctor._lightroom_running() is False


def test_mac_process_list_failure_means_unknown(monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("no ps")

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert doctor._lightroom_running() is None


def test_windows_still_uses_tasklist(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Completed("Lightroom.exe   1234 Console\n")

    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor._lightroom_running() is True
    assert seen["cmd"][0] == "tasklist"
    assert doctor._lightroom_process_label() == "Lightroom.exe"
