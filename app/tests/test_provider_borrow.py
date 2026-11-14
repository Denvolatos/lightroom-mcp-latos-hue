# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1：选了 Claude 但没装/没登录/还没连上时，窗口继续用自己的 Bridge；常驻 claude 那条通道连上后才借用。"""
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

import settings as st


@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "app_settings.json").write_text('{"provider": "claude"}', encoding="utf-8")
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    a._state_file = tmp_path / "claude_side.json"
    yield a
    a._shutdown()


class FakeClaude:
    id = "claude"
    busy = False
    spawned_at = None

    def __init__(self, start_result=True, alive=True):
        self._start, self.alive, self.closed = start_result, alive, False

    def start(self, env=None):
        if isinstance(self._start, Exception):
            raise self._start
        return self._start

    def close(self):
        self.closed = True

    def status(self):
        return {"available": True, "state": "ready", "reason": "", "next_step": ""}


def _patch_services(monkeypatch):
    import main
    monkeypatch.setattr(main, "PreviewManager", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main, "PreviewServer", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main, "Backend", lambda *a, **k: MagicMock())


def _side(path, connected=True, rpc_port=50123):
    path.write_text(json.dumps({"t": time.time(), "connected": connected, "rpc_port": rpc_port}), encoding="utf-8")


def test_claude_resident_starts_with_own_bridge(api):
    assert api._persistent is True and api._borrowing is False
    assert api._lr._remote is None                         # 窗口自己的 Bridge，不依赖 claude 进程


@pytest.mark.parametrize("result", [False, OSError("找不到 claude")])
def test_failed_claude_start_keeps_own_bridge(api, monkeypatch, result):
    _patch_services(monkeypatch)
    lr = api._lr
    api._provider = api._session = FakeClaude(start_result=result, alive=False)
    assert api._start_resident() is False
    time.sleep(0.05)
    assert api._borrowing is False and api._lr is lr and api._lr._remote is None


def test_switches_to_borrowed_channel_only_after_side_connects(api, monkeypatch):
    _patch_services(monkeypatch)
    p = FakeClaude()
    api._provider = api._session = p
    _side(api._state_file, connected=False)
    t = threading.Thread(target=api._watch_side, args=(p, 0.01), daemon=True)
    t.start()
    time.sleep(0.1)
    assert api._borrowing is False and api._lr._remote is None          # 侧通道还没连上：不切
    _side(api._state_file, connected=True)
    t.join(2)
    assert not t.is_alive() and api._borrowing is True and api._lr._remote is not None
    for svc in (api._import, api._export, api._photolib, api._pick, api._apply, api._lib):
        assert svc.lr is api._lr


def test_dead_claude_with_fresh_state_file_does_not_switch(api, monkeypatch):
    _patch_services(monkeypatch)
    p = FakeClaude(alive=False)
    api._provider = api._session = p
    _side(api._state_file, connected=True)
    t = threading.Thread(target=api._watch_side, args=(p, 0.01), daemon=True)
    t.start()
    time.sleep(0.1)
    assert api._borrowing is False
    api._provider = FakeClaude()                           # 来源换掉：等待线程自己结束
    t.join(2)
    assert not t.is_alive() and api._borrowing is False


def test_does_not_switch_while_a_request_is_running(api, monkeypatch):
    _patch_services(monkeypatch)
    p = FakeClaude()
    api._provider = api._session = p
    _side(api._state_file, connected=True)
    api._busy = True
    t = threading.Thread(target=api._watch_side, args=(p, 0.01), daemon=True)
    t.start()
    time.sleep(0.1)
    assert api._borrowing is False
    api._busy = False
    t.join(2)
    assert api._borrowing is True


def test_shutdown_stops_the_watcher(api):
    p = FakeClaude(alive=False)
    api._provider = api._session = p
    t = threading.Thread(target=api._watch_side, args=(p, 0.01), daemon=True)
    t.start()
    api._closing.set()
    t.join(2)
    assert not t.is_alive()
