# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""main.Api 里 AI 链路的修复（1.1.1）：send 的忙检查加锁、被拒绝的那次不清理；挑片写入/撤销在 AI 忙时拒绝。
假 CLI、假 Lightroom，不联网、不调用真实模型。"""
from unittest.mock import MagicMock

import pytest

import settings as st


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    (tmp_path / "app_settings.json").write_text('{"provider": "claude"}', encoding="utf-8")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def test_rejected_send_does_not_clean_up_the_running_turn(api):
    assert api._pick_acquire() is True                       # 另一项 AI 任务正在进行
    api._hub.finish_turn = MagicMock()
    api._hub.end_turn = MagicMock()
    api._provider.send = MagicMock()
    r = api.send("你好")
    assert r["ok"] is False
    assert api._busy is True                                 # 不把别人的“忙”清掉
    api._hub.finish_turn.assert_not_called()
    api._hub.end_turn.assert_not_called()
    api._provider.send.assert_not_called()
    api._pick_release()


def test_send_checks_busy_under_lock(api):
    """检查与置位在同一把锁里：锁被别人持有时 send 等待，拿到锁后看到的是最新的忙标记。"""
    import threading
    api._provider.send = MagicMock()
    out = {}
    with api._lock:
        t = threading.Thread(target=lambda: out.setdefault("r", api.send("你好")))
        t.start()
        t.join(0.3)
        assert t.is_alive()                                  # 在等锁
        api._busy = True                                     # 持锁期间别人置了忙
    t.join(3)
    assert out["r"]["ok"] is False
    api._busy = False


@pytest.mark.parametrize("call", ["confirm", "undo"])
def test_pick_apply_refused_while_ai_busy(api, call):
    api._apply = MagicMock()
    assert api._pick_acquire() is True
    r = api.pick_apply_confirm(["A"]) if call == "confirm" else api.pick_apply_undo()
    assert r["ok"] is False and r.get("busy") is True
    api._apply.confirm.assert_not_called()
    api._apply.undo.assert_not_called()
    api._pick_release()
    api._apply.confirm.return_value = {"ok": True}
    api._apply.undo.return_value = {"ok": True, "results": []}
    r = api.pick_apply_confirm(["A"]) if call == "confirm" else api.pick_apply_undo()
    assert r["ok"] is True


# ---- 挑片 / 记成经验用独立的一次性会话（1.1.1）------------------------
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import claude_bridge as cb  # noqa: E402
import library_service  # noqa: E402
from providers.claude_provider import ClaudeProvider, OneShot  # noqa: E402


class FakeOne:
    def __init__(self, fork):
        self.fork, self.sent, self.stopped = fork, [], 0

    def send(self, text, on_event, **options):
        self.sent.append((text, options))

    def stop(self):
        self.stopped += 1


def test_pick_and_record_use_one_shot_not_chat_session(api, monkeypatch):
    made = []
    api._persistent = True
    api._provider.send = MagicMock()
    monkeypatch.setattr(api._provider, "one_shot", lambda fork=False: made.append(FakeOne(fork)) or made[-1])
    token = api._hub.begin_session()
    api._pick_send("挑片提示", lambda e: None)
    api._pick_send(library_service.build_record_prompt(), lambda e: None)
    api._provider.send.assert_not_called()                    # 聊天会话没被用到
    assert [m.fork for m in made] == [False, True]            # 挑片不带上下文；记成经验从聊天会话分叉
    for m in made:
        assert m.sent[0][1]["extra_env"]["LRAPP_TOKEN"] == token and m.stopped >= 1
    assert api._hub.current_token() == token                  # 常驻会话的口令没被换掉


def test_pick_stop_stops_the_one_shot(api, monkeypatch):
    api._persistent = True
    started, release = threading.Event(), threading.Event()

    class Slow(FakeOne):
        def send(self, text, on_event, **options):
            started.set()
            release.wait(3)

        def stop(self):
            self.stopped += 1
            release.set()

    one = Slow(False)
    monkeypatch.setattr(api._provider, "one_shot", lambda fork=False: one)
    api._provider.stop = MagicMock()
    t = threading.Thread(target=api._pick_send, args=("p", lambda e: None))
    t.start()
    assert started.wait(3)
    api._pick_stop()
    t.join(3)
    assert not t.is_alive() and one.stopped >= 1
    api._provider.stop.assert_not_called()                    # 不去打断聊天会话


def test_claude_one_shot_fork_and_fresh(monkeypatch, tmp_path):
    session = MagicMock()
    session.session_id = "CHAT-1"
    p = ClaudeProvider(session=session, persistent=True)
    fresh, fork = p.one_shot(), p.one_shot(fork=True)
    assert isinstance(fresh, OneShot) and fresh.session.session_id is None
    assert fork.session.session_id == "CHAT-1" and fork.session.fork is True
    seen = {}
    monkeypatch.setattr(cb, "find_claude", lambda: "claude")
    monkeypatch.setattr(cb, "write_mcp_config", lambda d=None, **k: seen.setdefault("dir", d) or tmp_path / "x.json")

    def build(*a, **k):
        seen["resume"] = a[2]
        return [sys.executable, "-c", "print('')"]
    monkeypatch.setattr(cb, "build_command", build)
    monkeypatch.setattr("timing.TIMING_LOG", tmp_path / "t.jsonl")
    monkeypatch.setattr(cb, "WORKDIR", tmp_path)
    fork.session.workdir = tmp_path
    real_popen = cb.subprocess.Popen
    cmds = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda cmd, **k: cmds.append(cmd) or real_popen(cmd, **k))
    fork.send("x", lambda e: None, extra_env={})
    assert seen["resume"] == "CHAT-1" and cmds[0][-1] == "--fork-session"
    assert seen["dir"] != cb.write_mcp_config.__defaults__ and seen["dir"].name == "lrmcp_oneshot"
    assert session.send.call_count == 0                       # 常驻聊天会话没被写入


def test_one_shot_stop_kills_process(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "find_claude", lambda: "claude")
    monkeypatch.setattr(cb, "write_mcp_config", lambda *a, **k: tmp_path / "x.json")
    monkeypatch.setattr(cb, "build_command", lambda *a, **k: [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr("timing.TIMING_LOG", tmp_path / "t.jsonl")
    s = cb.ClaudeSession(tmp_path, mcp_dir=tmp_path / "one")
    out = []
    t = threading.Thread(target=s.send, args=("x", out.append))
    t0 = time.monotonic()
    t.start()
    while s._proc is None and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    proc = s._proc
    s.stop()
    t.join(10)
    assert not t.is_alive() and proc.poll() is not None
    assert any(e["type"] == "stopped" for e in out) and out[-1]["type"] == "done"
