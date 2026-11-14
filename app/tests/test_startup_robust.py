# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1 启动与关闭：每一步单独兜底、巡检一定启动、图库刷新放最后；启动时不向 Lightroom 要版本号；关闭时每一步都执行。"""
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
    yield a
    for name in ("_autolaunch", "_backend", "_preview", "_photolib", "_provider", "_hub", "_lr"):
        setattr(a, name, MagicMock())
    a._shutdown()


def _mock_parts(api, order):
    def rec(name, boom=False):
        def f(*a, **k):
            order.append(name)
            if boom:
                raise RuntimeError("端口被占用")
            return False
        return f
    api._autolaunch = MagicMock(start=rec("autolaunch"))
    api._lr = MagicMock(start=rec("lr"))
    api._backend = MagicMock(start=rec("backend"))
    api._updates = MagicMock(start_background=rec("updates"))
    api._preview = MagicMock()
    api._preview.server.start = rec("preview_server", boom=True)        # 预览服务绑定端口失败
    api._photolib = MagicMock(refresh=rec("refresh"))
    api._photolib.server.start = rec("photolib_server")
    api._start_resident = rec("claude", boom=True)                       # claude 启动抛了意外的异常


def test_background_start_survives_failures_and_backend_starts_first(api):
    order, events = [], []
    _mock_parts(api, order)
    api._emit = events.append
    api._start_background()
    assert order.index("backend") < order.index("refresh") and order[-1] == "refresh"
    assert {"backend", "photolib_server", "refresh", "updates"} <= set(order)
    errs = [e["message"] for e in events if e.get("type") == "error"]
    assert len(errs) == 2 and any("预览服务" in m for m in errs) and any("AI 助手" in m for m in errs)
    assert api._startup_errors == ["AI 助手", "预览服务"]


def test_startup_settings_do_not_query_lightroom(api):
    api._lr = MagicMock(connected=True, plugin_version="1.1.0")
    r = api.get_settings(False)
    assert r["about"]["lightroom_version"] is None
    api._lr._bridge.call.assert_not_called()



# ---------------------------------------------------------------- 打开设置 / 向导：不重复跑登录检测，版本号限时 + 缓存
class CountingProvider:
    def __init__(self, pid):
        self.id, self.calls = pid, 0

    def status(self):
        self.calls += 1
        return {"available": True, "state": "ready", "reason": "已安装并已登录。", "next_step": ""}


class FakeProbe:
    def __init__(self):
        self._claude, self._codex = CountingProvider("claude"), CountingProvider("codex")


def test_settings_reuse_one_probe_for_the_other_provider(api, monkeypatch):
    import main
    made = []
    monkeypatch.setattr(main, "StatusProbe", lambda: made.append(1) or FakeProbe())
    monkeypatch.setattr(main.lr_autostart, "find_lightroom", lambda c: None)
    api._probe = None
    cur = CountingProvider("claude")
    api._provider = cur
    for _ in range(3):
        r = api.get_settings(True)
        assert {p["id"] for p in r["providers"]} >= {"claude", "codex"}
    assert made == [1]                                      # 探测器只建一次
    assert cur.calls == 3 and api._probe._codex.calls == 3 and api._probe._claude.calls == 0


def test_wizard_only_checks_the_selected_provider(api, monkeypatch):
    import main
    monkeypatch.setattr(main, "StatusProbe", FakeProbe)
    api._probe = None
    cur = CountingProvider("claude")
    api._provider = cur
    for _ in range(3):
        assert api._wizard_provider()["id"] == "claude"
    assert cur.calls == 3 and (api._probe is None or api._probe._codex.calls == 0)
    api._settings.data["provider"] = "codex"                 # 设置里换了来源、还没开新对话
    assert api._wizard_provider()["available"] is True and api._probe._codex.calls == 1 and cur.calls == 3


def test_about_waits_briefly_and_caches_the_lightroom_version(api, monkeypatch):
    import threading
    import time
    import main
    monkeypatch.setattr(main, "ABOUT_WAIT_SECONDS", 0.05)
    release = threading.Event()
    bridge = MagicMock()

    def slow_call(cmd, timeout):
        release.wait(2)
        return {"lightroom_version": "15.0"}
    bridge.call.side_effect = slow_call
    api._lr = MagicMock(connected=True, _bridge=bridge)
    api._lr_ver_cache = None
    t0 = time.monotonic()
    assert api._about()["lightroom_version"] is None and time.monotonic() - t0 < 1     # Lightroom 忙：不等它
    release.set()
    for _ in range(100):
        if getattr(api, "_lr_ver_cache", None):
            break
        time.sleep(0.01)
    assert api._about(None)["lightroom_version"] == "15.0"                         # 结果已经记进缓存
    assert api._about()["lightroom_version"] == "15.0" and bridge.call.call_count == 1
