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


@pytest.mark.parametrize("confirm_on", [True, False])
def test_turn_end_marks_unresolved_rows(confirm_on, tmp_path):
    t = adj.AdjustmentTracker(confirm_on=confirm_on, edit_dir=tmp_path)
    t.observe({"type": "tool", "name": "lr_set_develop", "id": "T1", "input": {"changes": {"Exposure2012": 0.3}}})
    t.observe({"type": "tool", "name": "lr_set_develop", "id": "T2", "input": {"changes": {"Contrast2012": 5}}})
    t.observe({"type": "tool_result", "id": "T1", "text": '{"edit_id": "E1", "changes": []}', "is_error": False})
    assert t.observe({"type": "stopped"}) is False
    assert t.observe({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True}) is True
    st = {r["key"]: r["status"] for r in t.rows}
    assert st == {"Exposure2012": adj.STATUS_OK, "Contrast2012": adj.STATUS_NOT_RUN}
    assert t.observe({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": False}) is False
    # 迟到的结果不会再改终态行
    t.observe({"type": "tool_result", "id": "T2", "text": '{"edit_id": "E2", "changes": []}', "is_error": False})
    assert {r["key"]: r["status"] for r in t.rows}["Contrast2012"] == adj.STATUS_NOT_RUN


# ---- 空闲超时（1.1.1）-------------------------------------------------
import threading  # noqa: E402
import time  # noqa: E402

import confirm_hub as ch  # noqa: E402


def test_watchdog_touch_pause_and_total():
    now = [0.0]
    paused = [False]
    w = cb.IdleWatchdog(idle=10, total=100, paused=lambda: paused[0], clock=lambda: now[0])
    now[0] = 9; assert not w.expired()
    w.touch(); now[0] = 18; assert not w.expired()              # 收到事件后重新计时
    now[0] = 30; assert w.expired()
    w.touch(); paused[0] = True; now[0] = 60; assert not w.expired()   # 等确认期间不计时
    paused[0] = False; now[0] = 65; assert not w.expired()
    now[0] = 101; w.touch(); assert w.expired()                 # 总上限


def test_continuous_output_is_not_a_timeout(session):
    session.start()
    ev = []
    t0 = time.monotonic()
    session.send("ticker", ev.append, timeout=1)                 # 总共约 2 秒，但一直有输出
    assert time.monotonic() - t0 > 1.5
    assert ev[-1]["type"] == "done" and not ev[-1]["is_error"]
    assert not any(e["type"] == "error" for e in ev)


def test_waiting_confirm_card_pauses_timeout(session, monkeypatch):
    session.start()
    release = time.monotonic() + 2.0
    monkeypatch.setattr(ch, "waiting_for_user", lambda: time.monotonic() < release)
    ev = []
    t0 = time.monotonic()
    session.send("silent", ev.append, timeout=0.5)
    took = time.monotonic() - t0
    assert 2.0 <= took < 6
    assert any(e["type"] == "error" and e["message"] == cb.MSG_TIMEOUT for e in ev)


def test_total_cap_still_applies(session):
    session.start()
    ev = []
    session.send("ticker", ev.append, timeout=1, total=0.8)
    assert any(e["type"] == "error" and e["message"] == cb.MSG_TIMEOUT for e in ev) and ev[-1]["type"] == "done"


def test_confirm_hub_reports_waiting():
    hub = ch.ConfirmHub(lambda ev: None, timeout=5)
    assert not ch.waiting_for_user()
    t = threading.Thread(target=hub.request, args=("mcp__lightroom_mcp__lr_set_develop", {"changes": {"Exposure2012": 1}}))
    t.start()
    deadline = time.monotonic() + 3
    while not ch.waiting_for_user() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ch.waiting_for_user()
    hub.cancel_all()
    t.join(3)
    assert not ch.waiting_for_user()
