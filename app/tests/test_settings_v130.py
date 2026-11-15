# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.3.0 新设置项：theme / font_size / panel_widths / preview_zoom 的合法性、旧设置兼容、保存读回。"""
import json

import pytest

import settings as st


@pytest.fixture
def store(tmp_path):
    return st.SettingsStore(tmp_path / "app_settings.json", restrict=lambda p: None)


def test_defaults():
    d = st.defaults()
    assert d["theme"] == "system" and d["font_size"] == "standard"
    assert d["panel_widths"] == {"left": 260, "right": 300} and d["preview_zoom"] == "fit"
    d["panel_widths"]["left"] = 1
    assert st.defaults()["panel_widths"]["left"] == 260           # 每次都是新字典


def test_old_settings_file_without_new_keys_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": 1, "provider": "claude", "provider_chosen": True, "preview_edge": 1536}), encoding="utf-8")
    s = st.SettingsStore(p, restrict=lambda x: None)
    assert s.data["theme"] == "system" and s.data["font_size"] == "standard"
    assert s.data["panel_widths"] == {"left": 260, "right": 300} and s.data["preview_zoom"] == "fit"
    assert s.data["preview_edge"] == 1536 and s.data["provider_chosen"] is True


@pytest.mark.parametrize("raw,expect", [
    ({"theme": "dark", "font_size": "xlarge", "panel_widths": {"left": 300, "right": 400}, "preview_zoom": 150},
     ("dark", "xlarge", {"left": 300, "right": 400}, 150)),
    ({"theme": "pink", "font_size": 3, "panel_widths": {"left": 100, "right": 999}, "preview_zoom": 5},
     ("system", "standard", {"left": 260, "right": 300}, "fit")),
    ({"theme": None, "font_size": [], "panel_widths": "wide", "preview_zoom": True},
     ("system", "standard", {"left": 260, "right": 300}, "fit")),
    ({"panel_widths": {"left": 250}, "preview_zoom": 400}, ("system", "standard", {"left": 250, "right": 300}, 400)),
    ({"panel_widths": {"left": 250.5, "right": "300"}, "preview_zoom": 12.5}, ("system", "standard", {"left": 260, "right": 300}, "fit")),
    ({"preview_zoom": "Fit"}, ("system", "standard", {"left": 260, "right": 300}, "fit")),
    ({"preview_zoom": 10, "panel_widths": {"left": 200, "right": 520}}, ("system", "standard", {"left": 200, "right": 520}, 10)),
])
def test_sanitize_loading(raw, expect):
    out = st.sanitize({"provider_chosen": True, **raw})
    assert (out["theme"], out["font_size"], out["panel_widths"], out["preview_zoom"]) == expect


@pytest.mark.parametrize("changes", [
    {"theme": "dark"}, {"theme": "paper"}, {"theme": "glass"}, {"theme": "system"},
    {"font_size": "small"}, {"font_size": "large"},
    {"panel_widths": {"left": 480, "right": 240}}, {"preview_zoom": "fit"}, {"preview_zoom": 400}, {"preview_zoom": 10},
])
def test_save_and_read_back(store, tmp_path, changes):
    r = store.update(changes)
    assert r["ok"], r
    again = st.SettingsStore(store.path, restrict=lambda p: None)
    for k, v in changes.items():
        assert again.data[k] == v


@pytest.mark.parametrize("changes,key", [
    ({"theme": "Dark"}, "theme"), ({"theme": 1}, "theme"), ({"theme": None}, "theme"),
    ({"font_size": "huge"}, "font_size"), ({"font_size": True}, "font_size"),
    ({"panel_widths": {"left": 199, "right": 300}}, "panel_widths"),
    ({"panel_widths": {"left": 260, "right": 521}}, "panel_widths"),
    ({"panel_widths": {"left": 260.0, "right": 300}}, "panel_widths"),
    ({"panel_widths": {"left": True, "right": 300}}, "panel_widths"),
    ({"panel_widths": {"left": "260", "right": 300}}, "panel_widths"),
    ({"panel_widths": {"left": 260, "right": 300, "middle": 5}}, "panel_widths"),
    ({"panel_widths": [260, 300]}, "panel_widths"), ({"panel_widths": None}, "panel_widths"),
    ({"preview_zoom": 9}, "preview_zoom"), ({"preview_zoom": 401}, "preview_zoom"), ({"preview_zoom": "100"}, "preview_zoom"),
    ({"preview_zoom": 100.5}, "preview_zoom"), ({"preview_zoom": True}, "preview_zoom"), ({"preview_zoom": None}, "preview_zoom"),
    ({"preview_zoom": "fill"}, "preview_zoom"),
])
def test_invalid_values_rejected_and_nothing_saved(store, changes, key):
    before = dict(store.data)
    r = store.update({**changes, "theme" if key != "theme" else "font_size": "dark" if key != "theme" else "large"})
    assert not r["ok"] and key in r["errors"] and r["errors"][key]
    assert store.data == before and not store.path.exists()


def test_partial_panel_widths_keeps_the_other_side(store):
    assert store.update({"panel_widths": {"left": 300, "right": 400}})["ok"]
    assert store.update({"panel_widths": {"left": 310}})["ok"]
    assert store.data["panel_widths"] == {"left": 310, "right": 400}


def test_new_keys_do_not_disturb_other_settings(store):
    assert store.update({"preview_edge": 2048, "confirm_default": False})["ok"]
    assert store.update({"theme": "dark"})["ok"]
    assert store.data["preview_edge"] == 2048 and store.data["confirm_default"] is False and store.data["schema"] == st.SCHEMA_VERSION


def test_theme_values_and_legacy_light():
    assert st.clean_theme("paper") == "paper" and st.clean_theme("glass") == "glass"
    assert st.clean_theme("light") == "paper"                      # 旧值按浅色纸感处理
    assert st.clean_theme("blue") is None and st.clean_theme(3) is None
