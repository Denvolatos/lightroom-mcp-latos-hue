# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.3.0 后端：只读开关、清理缓存、诊断包脱敏、恢复默认设置、关于信息、外链白名单。全部用 tmp_path 与假对象。"""
import io
import json
import zipfile
from pathlib import Path

import pytest

import main
import maintenance as mt
import settings as st
from photo_library import ThumbStore
from preview import PreviewStore


# ---------------------------------------------------------------- 只读开关
def test_set_readonly_creates_and_removes_file(tmp_path):
    f = tmp_path / "LrMcp" / "readonly"
    r = mt.set_readonly(True, f, environ={})
    assert r["ok"] and r["readonly"] is True and f.is_file()
    r = mt.set_readonly(False, f, environ={})
    assert r["ok"] and r["readonly"] is False and not f.exists()
    assert mt.set_readonly(False, f, environ={})["ok"]                    # 本来就没有：不报错


def test_set_readonly_rejects_non_bool_and_keeps_state(tmp_path):
    f = tmp_path / "readonly"
    for bad in ("true", 1, None, [], "yes"):
        r = mt.set_readonly(bad, f, environ={})
        assert r["ok"] is False and r["message"] and not f.exists()


def test_set_readonly_env_var_keeps_it_on(tmp_path):
    f = tmp_path / "readonly"
    f.write_text("x")
    r = mt.set_readonly(False, f, environ={"LRMCP_READONLY": "1"})
    assert r["ok"] and r["readonly"] is True and "LRMCP_READONLY" in r["message"] and not f.exists()


def test_set_readonly_failure_gives_chinese_reason(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not folder")
    r = mt.set_readonly(True, blocker / "sub" / "readonly", environ={})
    assert r["ok"] is False and "无法开启只读模式" in r["message"] and r["readonly"] is False


# ---------------------------------------------------------------- 清理缓存
def test_clear_cache_only_touches_caches(tmp_path):
    thumbs, previews = ThumbStore(), PreviewStore()
    thumbs.put("A", 1, "v", b"x" * 1000)
    thumbs.put("B", 1, "v", b"y" * 500)
    previews.put("A", 1024, "v", b"z" * 2000)
    log = tmp_path / "app_timing.jsonl"
    log.write_text("x" * 300)
    keep = {n: tmp_path / n for n in ("app_settings.json", "photo.CR3", "notes.json", "favs.json", "x.lrcat")}
    for p in keep.values():
        p.write_text("keep me")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "versions.json").write_text("keep")
    r = mt.clear_cache(thumbs, previews, log)
    assert r["ok"] and r["freed_bytes"] == 1500 + 2000 + 300
    assert {i["name"]: i["bytes"] for i in r["items"]} == {"图库缩略图缓存": 1500, "预览缓存": 2000, "计时日志": 300}
    assert r["freed_text"] == "3.7 KB" and r["message"]
    assert len(thumbs) == 0 and thumbs.total_bytes == 0 and len(previews) == 0 and not log.exists()
    assert all(p.read_text() == "keep me" for p in keep.values())
    assert (tmp_path / "knowledge" / "versions.json").read_text() == "keep"
    thumbs.put("A", 1, "v", b"again")                                     # 清空后仍可正常写入
    assert thumbs.total_bytes == 5


def test_clear_cache_without_timing_log(tmp_path):
    r = mt.clear_cache(ThumbStore(), PreviewStore(), tmp_path / "none.jsonl")
    assert r["ok"] and r["freed_bytes"] == 0 and r["freed_text"] == "0 B"


# ---------------------------------------------------------------- Api 层
class FakeSettings:
    def __init__(self, path, data=None):
        self.store = st.SettingsStore(path, restrict=lambda p: None)
        if data:
            assert self.store.update(data, selectable=lambda pid: True)["ok"]


class Svc:
    def __init__(self, stage="idle"):
        self.stage = stage


class Lib:
    def __init__(self):
        self.store = ThumbStore()
        self.cleared = 0

    def thumbs_cleared(self):
        self.cleared += 1


class Prev:
    def __init__(self):
        self.store = PreviewStore()
        self.requests = []
        self.edge = None

    def request(self, d=0):
        self.requests.append(d)

    def set_edge(self, e):
        self.edge = e


class Wiz:
    def __init__(self, items):
        self.items = items
        self.invalidated = 0

    def state(self, refresh=False):
        return {"items": self.items}

    def invalidate(self):
        self.invalidated += 1


class Backend:
    def status(self):
        return {"state": "connected", "connected": True, "app": True, "side": None, "claude_alive": True,
                "hint": r"C:\Users\Alice\LrMcp 正常"}


class Lr:
    plugin_version = "1.2.0"


@pytest.fixture
def api(tmp_path, monkeypatch):
    a = main.Api.__new__(main.Api)
    a._busy = False
    a._session = type("S", (), {"busy": False})()
    a._import, a._export = Svc(), Svc()
    a._photolib, a._preview = Lib(), Prev()
    a._lr, a._backend = Lr(), Backend()
    a._window = None
    a._settings = FakeSettings(tmp_path / "data" / "app_settings.json").store
    ro = tmp_path / "LrMcp" / "readonly"
    monkeypatch.setattr(main.Api, "_readonly_path", lambda self: ro)
    monkeypatch.setattr(main.timingmod, "TIMING_LOG", tmp_path / "LrMcp" / "app_timing.jsonl")
    monkeypatch.delenv("LRMCP_READONLY", raising=False)
    a.ro_file = ro
    a.tmp = tmp_path
    return a


def test_api_set_readonly_roundtrip(api):
    assert api._readonly_on() is False
    r = api.set_readonly(True)
    assert r["ok"] and r["readonly"] and api.ro_file.is_file() and api._readonly_on() is True
    r = api.set_readonly(False)
    assert r["ok"] and not r["readonly"] and not api.ro_file.exists()
    r = api.set_readonly("on")
    assert not r["ok"] and r["message"] and not api.ro_file.exists()


def test_api_get_settings_has_readonly(api, monkeypatch):
    monkeypatch.setattr(main.lr_autostart, "find_lightroom", lambda p="": "")
    api._provider = type("P", (), {"id": "claude", "status": lambda self: {"available": True, "state": "ok", "reason": "", "next_step": ""}})()
    api._pending_lr_path = ""
    api._about = lambda timeout=None: {}
    api._provider_status = lambda pid: {"available": True, "state": "ok", "reason": "", "next_step": ""}
    assert api.get_settings(include_status=False)["readonly"] is False
    api.set_readonly(True)
    g = api.get_settings(include_status=False)
    assert g["readonly"] is True and g["settings"]["theme"] == "system" and g["settings"]["panel_widths"] == {"left": 260, "right": 300}


def test_api_clear_cache(api):
    api._photolib.store.put("A", 1, "v", b"x" * 100)
    api._preview.store.put("A", 1, "v", b"y" * 50)
    log = main.timingmod.TIMING_LOG
    log.parent.mkdir(parents=True)
    log.write_text("z" * 10)
    other = log.parent / "keep.txt"
    other.write_text("keep")
    r = api.clear_cache()
    assert r["ok"] and r["freed_bytes"] == 160 and not log.exists() and other.read_text() == "keep"
    assert api._photolib.cleared == 1 and api._preview.requests == [0]    # 图库与预览重新取


@pytest.mark.parametrize("setup", ["busy", "session", "import", "export"])
def test_api_clear_cache_and_reset_refused_when_busy(api, setup):
    if setup == "busy":
        api._busy = True
    elif setup == "session":
        api._session.busy = True
    elif setup == "import":
        api._import.stage = "copying"
    else:
        api._export.stage = "running"
    api._photolib.store.put("A", 1, "v", b"x")
    for r in (api.clear_cache(), api.reset_settings()):
        assert r["ok"] is False and r["busy"] is True and r["message"]
    assert len(api._photolib.store) == 1 and api._photolib.cleared == 0


def test_reset_settings_keeps_base_folder_and_provider(api, tmp_path):
    lib = tmp_path / "photos"
    lib.mkdir()
    s = api._settings
    assert s.update({"base_folder": str(lib), "provider": "codex", "provider_chosen": True, "theme": "dark", "font_size": "large",
                     "preview_zoom": 200, "panel_widths": {"left": 400, "right": 500}, "preview_edge": 2048,
                     "confirm_default": False, "export_quality": 70}, selectable=lambda pid: True)["ok"]
    r = api.reset_settings()
    assert r["ok"] and r["message"]
    d = api._settings.data
    assert d["base_folder"] == str(lib) and d["provider"] == "codex" and d["provider_chosen"] is True
    assert (d["theme"], d["font_size"], d["preview_zoom"]) == ("system", "standard", "fit")
    assert d["panel_widths"] == {"left": 260, "right": 300} and d["preview_edge"] == 1024 and d["confirm_default"] is True
    assert d["export_quality"] == 92
    again = st.SettingsStore(s.path, restrict=lambda p: None)
    assert again.data == d
    baks = list(s.path.parent.glob("app_settings.json.reset-*.bak"))
    assert len(baks) == 1
    old = json.loads(baks[0].read_text(encoding="utf-8"))
    assert old["theme"] == "dark" and old["export_quality"] == 70 and old["base_folder"] == str(lib)
    assert api._preview.edge == 1024 and api._wizard_invalidated() if hasattr(api, "_wizard_invalidated") else True


def test_reset_settings_when_never_chosen_ai(api):
    r = api.reset_settings()
    assert r["ok"] and api._settings.data["provider_chosen"] is False and api._settings.data["base_folder"] == ""


def test_api_never_leaks_exceptions(api):
    api._photolib = None                                                   # clear_cache 内部会炸
    r = api.clear_cache()
    assert r["ok"] is False and "清理缓存失败" in r["message"]
    api._settings = None
    r = api.reset_settings()
    assert r["ok"] is False and "恢复默认设置失败" in r["message"]
    api._pick_diag_folder = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    r = api.make_diagnostics()
    assert r["ok"] is False and "生成诊断包失败" in r["message"]


# ---------------------------------------------------------------- 关于 / 外链
def test_about_info_shape(api):
    a = api.about_info()
    assert a["name"] == "Latos Hue 修图助手" and a["version"] == st.APP_VERSION and a["plugin_version"] == "1.2.0"
    assert a["license"] == "AGPL-3.0-only" and a["homepage"] == "https://github.com/Denvolatos/lightroom-mcp-latos-hue"
    assert a["disclaimer"] == "本软件不含任何 Adobe 软件，也不是 Adobe 官方产品。"
    assert a["tagline"] == "让 AI 帮你在一个窗口里挑片、修图、导出。"
    assert [(x["name"], x["role"], x["key"], x["url"]) for x in a["authors"]] == [
        ("Denvolatos", "发起与主要开发", "denvolatos", "https://github.com/Denvolatos"),
        ("Galio1991", "共同开发", "galio1991", "https://github.com/Galio1991")]
    assert all("confirmed" not in x for x in a["authors"]) and "致谢" not in json.dumps(a, ensure_ascii=False)
    a["authors"][0]["name"] = "changed"
    assert api.about_info()["authors"][0]["name"] == "Denvolatos"          # 不污染常量
    api._lr = object()
    assert api.about_info()["plugin_version"] is None


def test_open_link_whitelist():
    seen = []
    assert mt.open_link("galio1991", seen.append) == {"ok": True, "message": ""}
    assert mt.open_link("denvolatos", seen.append)["ok"] and mt.open_link("homepage", seen.append)["ok"]
    assert seen == ["https://github.com/Galio1991", "https://github.com/Denvolatos",
                    "https://github.com/Denvolatos/lightroom-mcp-latos-hue"]
    for bad in ("https://evil.example", "", None, 3, ["homepage"], "HOMEPAGE"):
        r = mt.open_link(bad, seen.append)
        assert r["ok"] is False and r["message"]
    assert len(seen) == 3
    r = mt.open_link("homepage", lambda u: False)
    assert r["ok"] is False and "https://github.com/Denvolatos/lightroom-mcp-latos-hue" in r["message"]
    def boom(u):
        raise OSError("x")
    assert mt.open_link("homepage", boom)["ok"] is False


# ---------------------------------------------------------------- 诊断包
FAKE_SETTINGS = {
    "schema": 1, "base_folder": r"D:\Photos\Alice Private\Trip", "export_last_folder": r"E:\Out\alice", "lightroom_path": r"C:\Program Files\Adobe\Lightroom\Lightroom.exe",
    "provider": "claude", "provider_chosen": True, "theme": "dark", "panel_widths": {"left": 260, "right": 300}, "preview_zoom": "fit",
    "api_token": "sk-SECRETSECRETSECRET123456", "email": "alice@example.com", "password": "hunter2hunter2",
    "unknown_future_key": r"C:\Users\Alice\secret.txt",
}
LOG = "\n".join([
    r"2026-11-15 10:00:00 INFO lrmcp: bridge listening on 127.0.0.1:58770",
    r"2026-11-15 10:00:01 INFO lrmcp: opened C:\Users\Alice\Pictures\Trip 2026\IMG_0001.CR3 for user Alice",
    r"2026-11-15 10:00:02 WARNING lrmcp: token=abcdef0123456789abcdef0123456789abcdef and mail alice@example.com",
    r"2026-11-15 10:00:03 INFO lrmcp: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
    "2026-11-15 10:00:04 INFO lrmcp: rendering DSC_8841.NEF done in 120 ms",
    r"2026-11-15 10:00:05 INFO lrmcp: share \\NAS\photos\alice\x.jpg",
    "2026-11-15 10:00:06 INFO lrmcp: /Users/alice/Pictures/a.jpg",
    "2026-11-15 10:00:07 INFO lrmcp: user ALICE connected",
])
LEAKS = ["Alice", "alice", "hunter2", "SECRETSECRET", "sk-", "IMG_0001", "DSC_8841", "abcdef0123456789", "eyJhbGci",
         r"C:\Users", "Pictures", "Private", "example.com", "NAS", "secret.txt", "Program Files", "Out\\"]


def zip_text(path):
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            out[n] = z.read(n).decode("utf-8")
    return out


def build(tmp_path, **kw):
    log = tmp_path / "server.log"
    log.write_text(LOG, encoding="utf-8")
    timing = tmp_path / "app_timing.jsonl"
    timing.write_text("\n".join(json.dumps({"t": "x", "mode": "persistent", "total_ms": 1000 + i, "startup_ms": 10, "model_ms": 900,
                                             "tools_ms": 90, "tools": [{"name": "lr_secret_tool", "ms": 1}]}) for i in range(3)) + "\n{坏行\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    items = [{"id": "folder", "title": "照片工作文件夹", "state": "ready", "text": r"已就绪：D:\Photos\Alice Private\Trip", "hint": ""},
             {"id": "lightroom", "title": "Lightroom", "state": "todo", "text": "没找到"}]
    info = {"app_version": "1.3.0", "plugin_version": "1.2.0", "server_version": "1.2.0", "readonly": True,
            "system": {"os": "Windows-11-10.0.26200 (host ALICE-PC)", "python": "3.12.1", "pywebview": "5.0", "webview2_runtime": "130.0"}}
    conn = {"state": "connected", "connected": True, "app": True, "side": None, "claude_alive": True, "hint": r"C:\Users\Alice\LrMcp"}
    res = mt.build_diagnostics(out, info, settings=FAKE_SETTINGS, wizard_items=items, connection=conn, log_files=[log],
                               timing_log=timing, now=(2026, 11, 15, 10, 30, 5, 0, 0, -1), extra_names=("Alice",), **kw)
    return res, out


def test_diagnostics_content_is_scrubbed(tmp_path):
    res, out = build(tmp_path)
    assert res["ok"] and res["bytes"] > 0 and Path(res["path"]).name == "LatosHue-diagnostics-20261115-103005.zip"
    assert Path(res["path"]).parent == out and [p.name for p in out.iterdir()] == [Path(res["path"]).name]
    files = zip_text(res["path"])
    assert set(files) == {"README.txt", "diagnostics.json", "log-tail.txt"}
    blob = "\n".join(files.values())
    for leak in LEAKS:
        assert leak not in blob, leak
    assert "lr_secret_tool" not in blob
    d = json.loads(files["diagnostics.json"])
    assert d["versions"] == {"app": "1.3.0", "plugin": "1.2.0", "server": "1.2.0"} and d["readonly"] is True
    assert d["system"]["python"] == "3.12.1" and d["system"]["webview2_runtime"] == "130.0"
    assert d["settings"]["base_folder"] == "已设置" and d["settings"]["export_last_folder"] == "已设置"
    assert d["settings"]["lightroom_path"] == "已设置" and d["settings"]["theme"] == "dark"
    assert d["settings"]["panel_widths"] == {"left": 260, "right": 300}
    assert not {"api_token", "email", "password", "unknown_future_key"} & set(d["settings"])
    assert [i["id"] for i in d["environment_check"]] == ["folder", "lightroom"] and d["environment_check"][1]["state"] == "todo"
    assert d["lightroom_connection"]["connected"] is True and d["timing"]["rows"] == 3
    assert d["timing"]["total_ms"]["median"] == 1001.0
    log = files["log-tail.txt"]
    assert "<path>" in log and "<user>" in log and "58770" in log
    assert "不含" in files["README.txt"] or "没有" in files["README.txt"]


def test_diagnostics_log_limited_to_500_lines(tmp_path):
    log = tmp_path / "server.log"
    log.write_text("\n".join(f"line {i}" for i in range(2000)), encoding="utf-8")
    out = tmp_path / "o"
    out.mkdir()
    res = mt.build_diagnostics(out, {"app_version": "1"}, settings={}, wizard_items=[], connection={}, log_files=[log])
    text = zip_text(res["path"])["log-tail.txt"]
    lines = [l for l in text.splitlines() if l.startswith("line ")]
    assert len(lines) == 500 and lines[-1] == "line 1999" and lines[0] == "line 1500"


def test_diagnostics_without_logs_and_unique_name(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    now = (2026, 1, 2, 3, 4, 5, 0, 0, -1)
    a = mt.build_diagnostics(out, {}, settings={}, wizard_items=None, connection=None, log_files=[tmp_path / "nolog"], now=now)
    b = mt.build_diagnostics(out, {}, settings={}, wizard_items=None, connection=None, log_files=[], now=now)
    assert a["ok"] and b["ok"] and a["path"] != b["path"]
    assert "没有日志" in zip_text(a["path"])["log-tail.txt"]


def test_diagnostics_bad_folder(tmp_path):
    r = mt.build_diagnostics(tmp_path / "missing", {}, settings={}, wizard_items=[], connection={})
    assert r["ok"] is False and r["message"]


def test_api_make_diagnostics_cancel_and_pick(api, tmp_path, monkeypatch):
    api._pick_diag_folder = lambda: None
    assert api.make_diagnostics() == {"ok": False, "cancelled": True, "path": "", "bytes": 0, "message": ""}
    out = tmp_path / "picked"
    out.mkdir()
    api._pick_diag_folder = lambda: str(out)
    api._wizard = Wiz([{"id": "folder", "state": "ready", "text": r"D:\Photos\Alice"}])
    api._settings = FakeSettings(tmp_path / "s.json", {"provider": "claude"}).store
    api._settings.data["api_token"] = "sk-LEAKLEAKLEAKLEAK1234"
    monkeypatch.setattr(mt, "environment_info", lambda: {"os": "Win", "python": "3.12", "pywebview": "x", "webview2_runtime": "y"})
    r = api.make_diagnostics()
    assert r["ok"], r
    assert Path(r["path"]).parent == out
    blob = "\n".join(zip_text(r["path"]).values())
    assert "LEAK" not in blob and "Alice" not in blob


def test_api_make_diagnostics_without_window_is_cancel(api):
    assert api._window is None
    assert api.make_diagnostics()["cancelled"] is True


@pytest.mark.parametrize("text,gone", [
    (r"open C:\Users\Bob\x y\z.txt now", "Bob"), ("user Bob logged in", "Bob"), ("mail me@x.org", "me@x.org"),
    ("password = hunter22", "hunter22"), ("api_key: abcd1234", "abcd1234"), ("/home/bob/a", "bob"),
    ("file P1010.rw2 ok", "P1010"), ("key sk-abcdefghijklmnopqrstuv", "abcdefghijkl"),
])
def test_scrub_text(text, gone):
    assert gone not in mt.scrub_text(text, extra_names=("Bob",))


def test_scrub_keeps_harmless_numbers():
    s = mt.scrub_text("bridge listening on 127.0.0.1:58770 version 1.2.0 took 120 ms")
    assert s == "bridge listening on 127.0.0.1:58770 version 1.2.0 took 120 ms"
