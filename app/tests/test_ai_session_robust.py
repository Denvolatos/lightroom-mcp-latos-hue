# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""常驻会话与“本次调整”表的健壮性（1.1.1）：单个事件出错不影响后续读取；changes 不是 dict 也不抛异常。"""
import sys
from pathlib import Path

import pytest

import adjustments as adj
import claude_bridge as cb
import persistent_session as ps

FAKE = str(Path(__file__).with_name("fake_claude.py"))


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "find_claude", lambda: "claude")
    monkeypatch.setattr(cb, "build_command", lambda *a, **k: [sys.executable, FAKE])
    monkeypatch.setattr(cb, "write_mcp_config", lambda *a, **k: tmp_path / "x.json")
    monkeypatch.setattr(ps, "INTERRUPT_GRACE", 1)
    monkeypatch.setattr("timing.TIMING_LOG", tmp_path / "t.jsonl")
    s = ps.PersistentSession(workdir=tmp_path)
    yield s
    s.shutdown()


def test_event_handler_error_does_not_stop_reader(session):
    session.start()
    seen = []

    def emit(ev):
        seen.append(ev["type"])
        if ev["type"] == "tool":
            raise AttributeError("界面处理出错")

    session.send("hello", emit, timeout=10)
    assert seen[-1] == "done" and "tool_result" in seen          # 出错之后的事件照样读到，这一轮正常结束
    ev = []
    session.send("hello", ev.append, timeout=10)                 # 读取线程还活着，下一轮照常
    assert ev[-1]["type"] == "done" and not ev[-1]["is_error"]


def test_done_emit_error_still_ends_turn(session):
    session.start()

    def emit(ev):
        if ev["type"] == "done":
            raise RuntimeError("x")

    session.send("hello", emit, timeout=10)                      # 不会卡到超时
    assert not session.busy


@pytest.mark.parametrize("changes", ['{"Exposure2012": 0.3}', "abc", ["Exposure2012"], 5, None])
def test_tracker_tolerates_non_dict_changes(changes, tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe({"type": "tool", "name": "lr_set_develop", "id": "T1", "input": {"changes": changes}})
    assert all(r["key"] == "Exposure2012" for r in t.rows)
    assert len(t.rows) == (1 if changes == '{"Exposure2012": 0.3}' else 0)
    t.observe({"type": "tool", "name": "lr_set_develop", "id": "T2", "input": "not a dict"})
    t.observe({"type": "tool_result", "id": "T1", "text": '{"edit_id": "E1", "changes": ["bad", 3]}', "is_error": False})
