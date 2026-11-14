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
