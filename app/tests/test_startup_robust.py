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

