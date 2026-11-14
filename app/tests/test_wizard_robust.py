# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1 向导：插件项只看窗口通道；AI 那一侧没连上归到 AI 项；旧版服务检查。"""
import wizard as wz

READY_AI = {"name": "Claude Code 命令行", "available": True, "state": "ready", "reason": "已安装并已登录。", "next_step": ""}


def checker(conn, provider=READY_AI, **kw):
    return wz.WizardChecker(lambda: {"base_folder": "C:\\x"}, find_lightroom=lambda c: "C:\\LR\\Lightroom.exe",
                            is_running=lambda: True, get_connection=lambda: conn, get_provider=lambda: provider,
                            isdir=lambda p: True, spawn=lambda fn: fn(), **kw)


def by_id(items):
    return {i["id"]: i for i in items}


def test_plugin_ready_when_window_channel_connected_even_if_ai_side_is_not():
    conn = {"state": "disconnected", "connected": False, "app": True, "side": False, "ai_side": False,
            "plugin_version": "1.1.0"}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.READY and "1.1.0" in items[wz.PLUGIN]["text"]
    ai = items[wz.AI]
    assert ai["state"] == wz.WAIT and "正在连接 Lightroom" in ai["text"] and ai["hint"] == wz.HINT_AI_SIDE


def test_plugin_todo_only_when_window_channel_is_down():
    conn = {"state": "disconnected", "connected": False, "app": False}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.TODO and items[wz.PLUGIN]["hint"] == wz.HINT_PLUGIN


def test_borrowed_channel_down_because_ai_process_gone_is_not_a_plugin_problem():
    conn = {"state": "disconnected", "connected": False, "app": False, "borrowing": True, "claude_alive": False}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.WAIT and "AI 助手" in items[wz.PLUGIN]["text"]


def test_ai_ready_when_side_connected_or_not_used():
    for side in (True, None):
        conn = {"state": "connected", "connected": True, "app": True, "ai_side": side}
        assert by_id(checker(conn).check())[wz.AI]["state"] == wz.READY


def test_old_connection_shape_without_app_key_still_works():
    items = by_id(checker({"state": "connected", "connected": True}).check())
    assert items[wz.PLUGIN]["state"] == wz.READY


# ---------------------------------------------------------------- 旧版服务
import ports  # noqa: E402

CUR = "1.1.1"


def _announce(d, port, pid, version=None):
    lines = [f"port={port}", "token=t", f"pid={pid}"] + ([f"version={version}"] if version is not None else [])
    (d / f"{port}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


class FakeProcs:
    """假的进程表：pid -> {"name", "cmdline"}；kill 只记下来并把进程从表里拿掉。"""

    def __init__(self, table):
        self.table, self.killed, self.queried = dict(table), [], []

    def info(self, pid):
        self.queried.append(pid)
        p = self.table.get(pid)
        return dict(p, pid=pid) if p else None

    def kill(self, pid):
        self.killed.append(pid)
        self.table.pop(pid, None)
        return True


def _setup(tmp_path):
    d = tmp_path / "servers"
    d.mkdir()
    _announce(d, 58771, 101, "0.9.0")          # 旧版 lrmcp.exe，活着
    _announce(d, 58772, 102, "1.0.2")          # 旧版，python 运行 lightroom_mcp
    _announce(d, 58773, 103, "1.1.1")          # 当前版本（本软件自己的）：不动
    _announce(d, 58774, 104, "1.0.0")          # 旧版，但进程号已被别的程序占用：不动
    _announce(d, 58775, 105, "1.0.0")          # 旧版，进程已经不在
    _announce(d, 58776, 106)                   # 没写版本：算旧；python 但不是 lightroom_mcp：不动
    procs = FakeProcs({
        101: {"name": "C:/Program Files/lrmcp/lrmcp.exe", "cmdline": ""},
        102: {"name": "C:/py/python.exe", "cmdline": "python.exe -m lightroom_mcp"},
        103: {"name": "C:/x/latoshue-helper.exe", "cmdline": ""},
        104: {"name": "C:/Windows/notepad.exe", "cmdline": ""},
        106: {"name": "C:/py/python.exe", "cmdline": "python.exe some_other_script.py"},
    })
    return d, procs


def test_version_compare():
    assert ports.is_older("1.0.2", "1.1.0") and ports.is_older("1.1", "1.1.1") and ports.is_older(None, "1.1.0")
    assert not ports.is_older("1.1.0", "1.1.0") and not ports.is_older("1.2.0", "1.1.0")
    assert not ports.is_older("1.1.0.0", "1.1.0")


def test_find_old_servers_only_live_old_lrmcp(tmp_path):
    d, procs = _setup(tmp_path)
    found = ports.find_old_servers(CUR, d, procs.info)
    assert [(s["port"], s["pid"]) for s in found] == [("58771", 101), ("58772", 102)]
    assert 103 not in procs.queried                           # 当前版本的服务根本不查进程


def test_stop_old_servers_kills_only_verified_and_removes_announcements(tmp_path):
    d, procs = _setup(tmp_path)
    r = ports.stop_old_servers(CUR, d, procs.info, procs.kill)
    assert r == {"stopped": ["58771", "58772"], "failed": []} and procs.killed == [101, 102]
    left = sorted(f.stem for f in d.glob("*.txt"))
    assert left == ["58773", "58774", "58775", "58776"]       # 没动的登记文件保留（失效的由 clean_stale_announcements 处理）
    assert ports.find_old_servers(CUR, d, procs.info) == []


def test_stop_rechecks_name_right_before_killing(tmp_path):
    d, procs = _setup(tmp_path)
    calls = {"n": 0}

    def info(pid):
        calls["n"] += 1
        p = procs.info(pid)
        if pid == 101 and calls["n"] > 2:                     # 查完之后、动手之前，进程号被别的程序占了
            return {"pid": pid, "name": "C:/Windows/explorer.exe", "cmdline": ""}
        return p
    r = ports.stop_old_servers(CUR, d, info, procs.kill)
    assert 101 not in procs.killed and (d / "58771.txt").exists() and r["stopped"] == ["58772"]


def test_kill_failure_is_reported_and_announcement_kept(tmp_path):
    d, procs = _setup(tmp_path)
    r = ports.stop_old_servers(CUR, d, procs.info, kill=lambda pid: False)
    assert r == {"stopped": [], "failed": ["58771", "58772"]} and (d / "58771.txt").exists()


def test_wizard_shows_old_servers_item_with_action(tmp_path):
    conn = {"state": "connected", "connected": True, "app": True}
    old = [{"port": "58771", "pid": 101}, {"port": "58772", "pid": 102}]
    items = checker(conn, get_old_servers=lambda: old).check()
    it = items[-1]
    assert it["id"] == wz.OLD_SERVERS and it["state"] == wz.TODO and it["count"] == 2
    assert "发现 2 个旧版服务在拖慢 Lightroom" in it["text"]
    assert it["action"] == "stop_old_servers" and it["action_label"] == "关闭旧版服务"


def test_wizard_hides_old_servers_item_when_none_or_check_fails():
    conn = {"state": "connected", "connected": True, "app": True}
    for fn in (lambda: [], lambda: (_ for _ in ()).throw(OSError("x"))):
        items = checker(conn, get_old_servers=fn).check()
        assert [i["id"] for i in items] == list(wz.ORDER)
        assert all(i["state"] == wz.READY for i in items)


def test_api_stop_old_servers_reports_and_invalidates(monkeypatch):
    import main
    api = main.Api.__new__(main.Api)
    inv = []
    api._wizard = type("W", (), {"invalidate": lambda self: inv.append(1)})()
    monkeypatch.setattr(main.portsmod, "stop_old_servers", lambda v: {"stopped": ["1", "2"], "failed": []})
    assert api.wizard_stop_old_servers() == {"ok": True, "stopped": 2, "message": ""} and inv == [1]
    monkeypatch.setattr(main.portsmod, "stop_old_servers", lambda v: {"stopped": [], "failed": ["3"]})
    r = api.wizard_stop_old_servers()
    assert r["ok"] is False and "没能关闭" in r["message"] and inv == [1, 1]
