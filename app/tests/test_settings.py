# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""设置读写与校验、AI 来源选择、设置对话框用到的后端接口。"""
import json
from pathlib import Path

import pytest

import settings as st
from providers import is_selectable


@pytest.fixture
def store(tmp_path):
    return st.SettingsStore(tmp_path / "app_settings.json", restrict=lambda p: None)


def test_defaults_do_not_probe_installed_tools(monkeypatch):
    """defaults() 被 sanitize 等处频繁调用：不能去找命令行，默认来源是固定值，且“尚未选择”。"""
    import claude_bridge
    from providers import codex_provider

    def boom():
        raise AssertionError("defaults() 不应该查找已安装的命令行")
    monkeypatch.setattr(claude_bridge, "find_claude", boom)
    monkeypatch.setattr(codex_provider, "find_codex", boom)
    d = st.defaults()
    assert d["provider"] == st.DEFAULT_PROVIDER == "claude" and d["provider_chosen"] is False
    assert not hasattr(st, "default_provider")


def test_gallery_folder_is_separate_from_import_folder(store, tmp_path):
    import_folder = tmp_path / "import"
    browse_folder = tmp_path / "browse"
    import_folder.mkdir()
    browse_folder.mkdir()
    assert store.update({"base_folder": str(import_folder)})["ok"]
    assert store.update({"gallery_folder": str(browse_folder)})["ok"]
    assert store.data["base_folder"] == str(import_folder)
    assert store.data["gallery_folder"] == str(browse_folder)


# ---------------------------------------------------------------- 读写
def test_defaults_when_file_missing(store):
    d = st.defaults()
    assert store.data == d
    assert d["base_folder"] == ""
    assert d["provider"] == "claude" and d["confirm_default"] is True and d["preview_edge"] == 1024


@pytest.mark.parametrize("content", ["{坏的", "", "[1,2]", "null", '"x"'])
def test_corrupt_file_does_not_crash(tmp_path, content):
    p = tmp_path / "s.json"
    p.write_text(content, encoding="utf-8")
    assert st.SettingsStore(p, restrict=lambda x: None).data == st.defaults()


def test_missing_and_invalid_fields_fall_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": 1, "confirm_default": "yes", "preview_edge": 999, "provider": 5,
                             "base_folder": "relative/path"}), encoding="utf-8")
    d = st.SettingsStore(p, restrict=lambda x: None).data
    assert d == {**st.defaults(), "provider_chosen": True}      # 文件存在 = 升级用户：视为已选择


def test_unknown_fields_are_kept_and_valid_ones_loaded(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"confirm_default": False, "preview_edge": 1536, "future_flag": {"a": 1}}), encoding="utf-8")
    s = st.SettingsStore(p, restrict=lambda x: None)
    assert s.data["confirm_default"] is False and s.data["preview_edge"] == 1536
    assert s.data["future_flag"] == {"a": 1}
    s.update({"preview_edge": 768})
    assert json.loads(p.read_text(encoding="utf-8"))["future_flag"] == {"a": 1}      # 保存时未知字段仍在


def test_existing_photo_folder_is_preserved(tmp_path):
    folder = tmp_path / "existing-photos"
    folder.mkdir()
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"base_folder": str(folder)}), encoding="utf-8")
    assert st.SettingsStore(config, restrict=lambda p: None).data["base_folder"] == str(folder)


def test_webview_cache_uses_selected_folder_and_is_cleaned(tmp_path, monkeypatch):
    import main

    class FakeApi:
        def __init__(self):
            self._settings = type("Settings", (), {"data": {"base_folder": str(tmp_path)}})()
            self.closed = False
        def _start_background(self):
            pass
        def _shutdown(self):
            self.closed = True

    api = FakeApi()
    paths = []
    monkeypatch.setattr(main, "Api", lambda: api)
    monkeypatch.setattr(main.webview, "create_window", lambda *a, **k: object())
    def start(_callback, *, storage_path, icon):
        cache = Path(storage_path)
        assert cache.parent == tmp_path and cache.name.startswith(".latoshue-webview-")
        assert cache.is_dir()
        (cache / "temporary").write_text("cache", encoding="utf-8")
        paths.append(cache)
    monkeypatch.setattr(main.webview, "start", start)
    main.main()
    assert api.closed and len(paths) == 1 and not paths[0].exists()


def test_atomic_write_roundtrip_and_restrict_called(tmp_path):
    called = []
    s = st.SettingsStore(tmp_path / "x" / "s.json", restrict=called.append)
    r = s.update({"confirm_default": False, "preview_edge": 2048})
    assert r["ok"]
    assert called and called[0].name.endswith(".tmp")
    assert not list((tmp_path / "x").glob("*.tmp"))
    again = st.SettingsStore(tmp_path / "x" / "s.json", restrict=lambda p: None).data
    assert again["confirm_default"] is False and again["preview_edge"] == 2048 and again["schema"] == st.SCHEMA_VERSION


def test_no_secret_like_fields_saved(store):
    store.update({"confirm_default": True})
    text = store.path.read_text(encoding="utf-8").lower()
    assert not any(w in text for w in ("token", "password", "api_key", "apikey", "secret"))


# ---------------------------------------------------------------- 文件夹
def test_folder_valid_existing(tmp_path):
    v = st.validate_folder(str(tmp_path))
    assert v["ok"] and v["exists"]


def test_folder_missing_but_creatable(tmp_path):
    v = st.validate_folder(str(tmp_path / "新建" / "子"))
    assert v["ok"] and not v["exists"]


@pytest.mark.parametrize("bad", ["", "   ", "relative\\dir", "\\\\server\\share\\x", "//server/share/x", "C:"])
def test_folder_rejects_non_absolute_or_network(bad):
    v = st.validate_folder(bad)
    assert not v["ok"] and v["message"]


def test_folder_rejects_drive_root():
    assert not st.validate_folder("C:\\")["ok"]


@pytest.mark.parametrize("sub", ["C:\\Windows", "C:\\Windows\\System32", "C:\\Program Files", "C:\\Program Files\\Foo",
                                 "C:\\Program Files (x86)\\Bar", "C:\\ProgramData\\X"])
def test_folder_rejects_system_dirs(sub):
    v = st.validate_folder(sub)
    assert not v["ok"] and "系统" in v["message"]


def test_folder_rejects_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    v = st.validate_folder(str(f))
    assert not v["ok"] and "文件" in v["message"]


def test_folder_rejects_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_writable", lambda d: False)
    assert "不可写" in st.validate_folder(str(tmp_path))["message"]
    assert "没有写入权限" in st.validate_folder(str(tmp_path / "new"))["message"]


def test_create_folder(tmp_path):
    target = tmp_path / "a" / "b"
    r = st.create_folder(str(target))
    assert r["ok"] and r["exists"] and target.is_dir()


# ---------------------------------------------------------------- update
def test_update_folder_needs_create_then_create(store, tmp_path):
    target = tmp_path / "图库"
    r = store.update({"base_folder": str(target)})
    assert not r["ok"] and r["needs_create"] and not target.exists()
    assert store.data["base_folder"] != str(target)                       # 未保存
    r = store.update({"base_folder": str(target)}, create_missing=True)
    assert r["ok"] and target.is_dir() and store.data["base_folder"] == str(target)


def test_update_invalid_folder_reports_reason_and_saves_nothing(store):
    r = store.update({"base_folder": "C:\\Windows\\x", "confirm_default": False})
    assert not r["ok"] and "系统" in r["errors"]["base_folder"]
    assert store.data["confirm_default"] is True and not store.path.exists()


def test_update_rejects_bad_values(store):
    r = store.update({"preview_edge": 1000, "confirm_default": "on"})
    assert not r["ok"] and set(r["errors"]) == {"preview_edge", "confirm_default"}
    assert not store.update({"preview_edge": True})["ok"]


def test_update_save_failure_is_reported(store, monkeypatch):
    def boom(data):
        raise PermissionError(13, "拒绝访问")
    monkeypatch.setattr(store, "save", boom)
    r = store.update({"confirm_default": False})
    assert not r["ok"] and "保存失败" in r["errors"]["_"]


# ---------------------------------------------------------------- AI 来源选择
def test_provider_selection_rules(store):
    assert store.update({"provider": "claude"}, selectable=is_selectable)["ok"]
    assert store.update({"provider": "codex"}, selectable=is_selectable)["ok"]
    for pid in ("api", "unknown", 5):
        r = store.update({"provider": pid}, selectable=is_selectable)
        assert not r["ok"] and "后续提供" in r["errors"]["provider"]
    assert store.data["provider"] == "codex"


# ---------------------------------------------------------------- 后端接口（Api）
@pytest.fixture
def api(tmp_path, monkeypatch):
    # 已有设置文件 = 升级用户：视为已经选过 AI 来源（全新安装的“请先选择”见 test_provider_choice.py）
    (tmp_path / "app_settings.json").write_text('{"provider": "claude"}', encoding="utf-8")
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def test_api_get_settings_shape(api):
    r = api.get_settings()
    assert r["settings"]["provider"] == "claude" and r["edges"] == [768, 1024, 1536, 2048]
    ids = [p["id"] for p in r["providers"]]
    assert ids == ["claude", "codex", "api"]
    assert [p["selectable"] for p in r["providers"]] == [True, True, False]
    assert set(r["about"]) == {"app_version", "lightroom_version", "plugin_version", "data_dir", "project_url"}
    assert r["about"]["data_dir"] == "~/LrMcp" and r["about"]["project_url"].endswith("Denvolatos/lightroom-mcp-latos-hue")


def test_api_save_applies_preview_edge_immediately(api):
    r = api.save_settings({"preview_edge": 1536})
    assert r["ok"] and api._preview.edge == 1536
    assert not api.save_settings({"preview_edge": 5})["ok"] and api._preview.edge == 1536


def test_api_save_accepts_codex_provider(api):
    r = api.save_settings({"provider": "codex"})
    assert r["ok"] and api._provider.id == "claude"


def test_api_save_settings_bad_input(api):
    assert not api.save_settings("x")["ok"]


def test_api_check_folder(api, tmp_path):
    assert api.check_folder(str(tmp_path))["ok"]
    assert not api.check_folder("C:\\Windows")["ok"]


def test_api_choose_folder_without_window(api):
    assert api.choose_folder() == {"ok": False, "path": ""}


def test_provider_switch_takes_effect_on_new_chat_only(api, monkeypatch):
    calls = []

    class Other:
        id = "other"
        alive = busy = False
        spawned_at = None

        def start(self, env=None): calls.append("start")
        def close(self): calls.append("close")
        def reset(self): calls.append("reset")
        def stop(self): pass

    import main
    monkeypatch.setattr(main, "is_selectable", lambda pid: True)
    monkeypatch.setattr(main, "create_provider", lambda pid, **k: Other())
    old = api._provider
    old_closed = []
    monkeypatch.setattr(old, "close", lambda: old_closed.append(1))
    monkeypatch.setattr(old, "reset", lambda: calls.append("old_reset"))
    assert api.save_settings({"provider": "claude"})["ok"]
    api._settings.data["provider"] = "other"                 # 模拟设置里选了另一个来源
    assert api._provider is old                              # 保存后不立刻切换
    api.reset()
    assert api._provider.id == "other" and old_closed and "start" in calls and "reset" not in calls
    assert api._backend.session is api._provider


def test_switch_to_codex_updates_import_and_export_services(api, monkeypatch):
    from unittest.mock import MagicMock
    import main

    new_lr = MagicMock()
    new_provider = MagicMock(id="codex")
    new_provider.id = "codex"
    monkeypatch.setattr(main, "LrService", lambda *a, **k: new_lr)
    monkeypatch.setattr(main, "create_provider", lambda *a, **k: new_provider)
    monkeypatch.setattr(main, "PreviewManager", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main, "PreviewServer", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main, "Backend", lambda *a, **k: MagicMock())
    api._settings.data["provider"] = "codex"
    assert api._apply_provider_choice()
    assert api._import.lr is new_lr and api._export.lr is new_lr


# ---------------------------------------------------------------- 浏览目录暂时不在：设置保留，只在运行时当作不可用
def test_sanitize_keeps_a_valid_looking_gallery_folder_that_does_not_exist_now(tmp_path):
    gone = tmp_path / "usb-drive-not-plugged"                       # 格式合法、目录现在不存在
    assert st.sanitize({"gallery_folder": str(gone)})["gallery_folder"] == str(gone.resolve())
    for bad in ("", "relative/x", r"\\server\share\x", r"C:\Windows", 5, None):
        assert st.sanitize({"gallery_folder": bad})["gallery_folder"] == ""      # 格式不合法的仍然丢弃


def test_saving_other_settings_does_not_clear_a_missing_gallery_folder(tmp_path):
    p = tmp_path / "s.json"
    gone = tmp_path / "usb-drive-not-plugged"
    p.write_text(json.dumps({"gallery_folder": str(gone)}), encoding="utf-8")
    s = st.SettingsStore(p, restrict=lambda x: None)
    assert s.update({"preview_edge": 1536})["ok"]
    assert json.loads(p.read_text(encoding="utf-8"))["gallery_folder"] == str(gone.resolve())


def test_new_gallery_choice_is_still_strict(tmp_path):
    s = st.SettingsStore(tmp_path / "s.json", restrict=lambda x: None)
    r = s.update({"gallery_folder": str(tmp_path / "nope")})
    assert not r["ok"] and "gallery_folder" in r["errors"] and s.data["gallery_folder"] == ""


def test_gallery_shows_unavailable_message_for_a_missing_browse_folder(tmp_path):
    from photo_library import MSG_BROWSE_GONE, PhotoLibrary

    class S:
        data = {"base_folder": str(tmp_path), "gallery_folder": str(tmp_path / "gone")}
    lib = PhotoLibrary.__new__(PhotoLibrary)
    import threading
    lib.settings, lib._lock, lib.lr = S(), threading.Lock(), type("L", (), {"connected": True})()
    got = []
    lib._set_error = got.append
    lib.refresh_sync()
    assert got == [MSG_BROWSE_GONE] and "暂时无法访问" in MSG_BROWSE_GONE
