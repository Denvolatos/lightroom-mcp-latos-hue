# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

import claude_bridge as cb
import persistent_session as ps

FAKE = str(Path(__file__).with_name("fake_claude.py"))


@pytest.fixture
def session(monkeypatch, tmp_path):
    calls = []

    def fake_build(prompt, mcp_config, session_id=None, claude_path="claude", confirm=True, persistent=False):
        calls.append({"resume": session_id, "persistent": persistent, "prompt": prompt})
        return [sys.executable, FAKE]

    monkeypatch.setattr(cb, "find_claude", lambda: "claude")
    monkeypatch.setattr(cb, "build_command", fake_build)
    monkeypatch.setattr(cb, "write_mcp_config", lambda *a, **k: tmp_path / "x.json")
    monkeypatch.setattr(ps, "INTERRUPT_GRACE", 1)
    monkeypatch.setattr("timing.TIMING_LOG", tmp_path / "t.jsonl")
    s = ps.PersistentSession(workdir=tmp_path)
    s.calls = calls
    yield s
    s.shutdown()


def run(s, text, **kw):
    ev = []
    s.send(text, ev.append, **kw)
    return ev


def pid_of(ev):
    return re.search(r"pid=(\d+)", "".join(e.get("text", "") for e in ev if e["type"] == "text")).group(1)


def test_two_turns_share_one_process(session):
    session.start()
    a, b = run(session, "hello"), run(session, "hello")
    assert [e["type"] for e in a if e["type"] != "text"] == ["session", "tool", "tool_result", "done"]
    assert pid_of(a) == pid_of(b)                            # 同一个进程，没有重新启动
    assert session.generation == 1 and session.session_id == "SESS-1"
    assert session.last_timing["mode"] == "persistent" and session.last_timing["tools"][0]["name"] == "lr_status"
    assert session.calls[0]["persistent"] is True and session.calls[0]["prompt"] is None


def test_stop_interrupts_but_keeps_process(session):
    session.start()
    ev, started = [], threading.Event()

    def emit(e):
        ev.append(e)
        if e["type"] == "text":
            started.set()

    t = threading.Thread(target=session.send, args=("slow", emit))
    t.start()
    assert started.wait(5)
    pid_before = session._proc.pid
    session.stop()
    t.join(5)
    assert not t.is_alive()
    kinds = [e["type"] for e in ev]
    assert "stopped" in kinds and kinds[-1] == "done" and "error" not in kinds   # 中断不当作错误展示
    assert session._proc.pid == pid_before and session.alive and session.restart_count == 0
    assert pid_of(run(session, "hello")) == str(pid_before)                     # 之后还能继续对话


def test_stop_falls_back_to_restart_when_interrupt_ignored(session):
    session.start()
    started = threading.Event()
    t = threading.Thread(target=session.send,
                         args=("stubborn", lambda e: started.set() if e["type"] == "text" else None))
    t.start()
    assert started.wait(5)
    pid_before = session._proc.pid
    session.stop()
    t.join(8)
    assert not t.is_alive()
    deadline = time.time() + 5
    while time.time() < deadline and not (session.alive and session._proc.pid != pid_before):
        time.sleep(0.1)
    assert session.alive and session._proc.pid != pid_before
    assert session.calls[-1]["resume"] == "SESS-1"                              # 用 --resume 保留对话


def test_reset_starts_fresh_conversation(session):
    session.start()
    a = run(session, "hello")
    session.reset()
    assert session.session_id is None and session.alive
    assert session.calls[-1]["resume"] is None
    assert pid_of(run(session, "hello")) != pid_of(a)


def test_process_death_reports_chinese_error_then_recovers(session):
    session.start()
    run(session, "hello")
    ev = run(session, "die")
    assert ev[-1]["type"] == "done" and ev[-1]["is_error"]
    assert any(e["type"] == "error" and "发生错误" in e["message"] for e in ev)
    ev2 = run(session, "hello")                                                 # 下一条消息自动重建
    assert ev2[-1]["type"] == "done" and not ev2[-1]["is_error"]
    assert session.restart_count >= 1 and session.calls[-1]["resume"] == "SESS-1"


def test_timeout_message(session):
    session.start()
    ev = run(session, "silent", timeout=1)
    assert any(e["type"] == "error" and e["message"] == cb.MSG_TIMEOUT for e in ev) and ev[-1]["type"] == "done"


def test_rejects_second_message_while_busy(session):
    session.start()
    started = threading.Event()
    t = threading.Thread(target=session.send,
                         args=("slow", lambda e: started.set() if e["type"] == "text" else None))
    t.start()
    assert started.wait(5)
    ev = run(session, "hello")
    assert ev[0]["type"] == "error" and "仍在处理" in ev[0]["message"] and ev[-1]["type"] == "done"
    session.stop()
    t.join(5)


def test_missing_claude(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "find_claude", lambda: None)
    s = ps.PersistentSession(workdir=tmp_path)
    ev = run(s, "hi")
    assert ev[0] == {"type": "error", "message": cb.MSG_NO_CLAUDE} and ev[-1]["is_error"]
    assert not s.alive


def test_command_for_persistent_mode():
    cmd = cb.build_command(None, Path("m.json"), "S", "claude", confirm=False, persistent=True)
    assert cmd[cmd.index("--input-format") + 1] == "stream-json" and "-p" in cmd
    assert None not in cmd and cmd[cmd.index("--permission-mode") + 1] == "default"   # 常驻模式一律走确认服务
    assert cmd[cmd.index("--permission-prompt-tool") + 1] == "mcp__lrapp_confirm__approve"
    allowed = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
    assert not any(w in a for a in allowed for w in cb.ENABLED_WRITE_TOOLS)
    assert cmd[cmd.index("--resume") + 1] == "S"


def test_mcp_config_uses_launcher_with_state_file(tmp_path):
    cfg = json.loads(cb.write_mcp_config(tmp_path, state_file=tmp_path / "s.json").read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["lightroom_mcp"]
    assert srv["args"][0].endswith("lr_launcher.py") and srv["env"]["LRAPP_BRIDGE_STATE"].endswith("s.json")
