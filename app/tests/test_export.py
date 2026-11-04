# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导出功能：选项校验、设置字段、ExportService 与 Api 接口（假 Lightroom、临时目录，不碰真实照片）。"""
import inspect
import os
import time

import pytest

import export_service as es
import importer as imp
import settings as st


@pytest.fixture(autouse=True)
def tmp_ok(monkeypatch):
    monkeypatch.setattr(imp, "BLOCKED_PARTS", tuple(b for b in imp.BLOCKED_PARTS if b != "/appdata/"))


class Settings:
    def __init__(self):
        self.data = st.defaults()

    def update(self, changes, **k):
        for key, v in changes.items():
            c = st.clean_export_field(key, v)
            assert c is not None, key
            self.data[key] = c
        return {"ok": True}


class FakeLr:
    def __init__(self, connected=True, photo=("P1", "DSC00001.ARW")):
        self.connected = connected
        self.photo = photo
        self.calls = []
        self.error = None
        self.delay = 0
        self.uncertain = False
        self.write = True

    def selected_detail(self):
        if not self.connected:
            return None
        if self.photo is None:
            return {"id": None, "name": None, "info": {}}
        return {"id": self.photo[0], "name": self.photo[1],
                "info": {"camera": "Sony", "width": 6000, "height": 4000, "format": "RAW"}}

    def export_photo(self, folder, fmt, long_edge, quality, metadata, bit_depth, photo="selected"):
        self.calls.append(dict(folder=folder, fmt=fmt, long_edge=long_edge, quality=quality, metadata=metadata,
                               bit_depth=bit_depth, photo=photo))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        if self.uncertain:
            return {"status": "uncertain", "message": "x"}
        name = es.preview_name("DSC00001.ARW", fmt, long_edge)
        path = os.path.join(folder, name)
        if self.write:
            with open(path, "wb") as f:
                f.write(b"x" * 2048)
        return {"status": "exported", "path": path, "file": name, "folder": folder, "bytes": 2048, "width": 1024,
                "height": 683, "format": fmt, "bit_depth": bit_depth if fmt == "tiff" else None,
                "quality": quality if fmt == "jpeg" else None}


def wait(pred, t=5):
    end = time.time() + t
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def svc(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    events = []
    lr = FakeLr()
    revealed = []
    s = es.ExportService(Settings(), lr, events.append, timeout=3, reveal_fn=revealed.append)
    s.events, s.revealed, s.out, s.lr_ = events, revealed, out, lr
    return s


GOOD = {"format": "jpeg", "size": 1024, "quality": 92, "bit_depth": 16, "metadata": "minimal"}


# ---------------------------------------------------------------- 选项校验
@pytest.mark.parametrize("patch", [
    {"format": "png"}, {"format": None}, {"format": 1}, {"size": 100}, {"size": 20001}, {"size": -1}, {"size": "1024"},
    {"size": 1024.5}, {"size": True}, {"quality": 39}, {"quality": 101}, {"quality": "90"}, {"quality": True},
    {"bit_depth": 12}, {"bit_depth": "16"}, {"bit_depth": True}, {"metadata": "none"}, {"metadata": ["all"]},
])
def test_validate_options_rejects(patch):
    o, why = es.validate_options({**GOOD, **patch})
    assert o is None and why


def test_validate_options_accepts_edges_and_ignores_extra():
    for size in (0, 256, 20000, 4096):
        for q in (40, 100):
            o, _ = es.validate_options({**GOOD, "size": size, "quality": q, "folder": "C:\\Windows", "path": "x"})
            assert o == {"format": "jpeg", "size": size, "quality": q, "bit_depth": 16, "metadata": "minimal"}
    assert es.validate_options("x")[0] is None and es.validate_options(None)[0] is None


def test_preview_name_rules():
    assert es.preview_name("DSC08206.ARW", "jpeg", 0) == "DSC08206_LrMCP_full.jpg"
    assert es.preview_name("DSC08206.ARW", "tiff", 1024) == "DSC08206_LrMCP_1024px.tif"
    assert es.preview_name("my photo (1).jpg", "jpeg", 2048) == "my_photo__1__LrMCP_2048px.jpg"
    assert es.preview_name(None, "jpeg", 0) == "photo_LrMCP_full.jpg"
    assert es.preview_name("a.b.CR3", "tiff", 0) == "a_b_LrMCP_full.tif"


# ---------------------------------------------------------------- 文件夹校验
def test_check_export_folder(tmp_path):
    ok, msg, p = es.check_export_folder(str(tmp_path))
    assert ok and p
    assert not es.check_export_folder(str(tmp_path / "nope"))[0]
    assert not es.check_export_folder("")[0] and not es.check_export_folder(None)[0]
    assert not es.check_export_folder("relative\\dir")[0]
    assert not es.check_export_folder("\\\\server\\share\\x")[0]
    assert not es.check_export_folder(os.environ.get("SystemRoot", "C:\\Windows"))[0]
    assert not es.check_export_folder("C:\\Program Files")[0]
    assert not es.check_export_folder("D:\\" + "a" * 500)[0]
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert not es.check_export_folder(str(f))[0]


def test_check_export_folder_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "DATA_DIR", tmp_path / "LrMcp")
    d = tmp_path / "LrMcp" / "exports"
    d.mkdir(parents=True)
    ok, msg, _ = es.check_export_folder(str(d))
    assert not ok and "数据目录" in msg


# ---------------------------------------------------------------- 设置字段
def test_settings_defaults_and_bad_values():
    d = st.defaults()
    assert d["export_format"] == "jpeg" and d["export_quality"] == 92 and d["export_bit_depth"] == 16
    assert d["export_size"] == 0 and d["export_metadata"] == "minimal" and d["export_last_folder"] == ""
    bad = {"export_last_folder": 5, "export_format": "png", "export_size": "big", "export_quality": 5,
           "export_bit_depth": 12, "export_metadata": ["x"]}
    out = st.sanitize(bad)
    for k in bad:
        assert out[k] == d[k]
    assert st.sanitize(None)["export_format"] == "jpeg"
    out = st.sanitize({"export_format": "tiff", "export_size": 2048, "export_quality": 100, "export_bit_depth": 8,
                       "export_metadata": "all", "export_last_folder": "relative\\x"})
    assert (out["export_format"], out["export_size"], out["export_quality"], out["export_bit_depth"],
            out["export_metadata"]) == ("tiff", 2048, 100, 8, "all")
    assert out["export_last_folder"] == ""


def test_settings_store_roundtrip_and_update_errors(tmp_path):
    store = st.SettingsStore(tmp_path / "s.json", restrict=lambda p: None)
    r = store.update({"export_format": "png"})
    assert not r["ok"] and "export_format" in r["errors"]
    r = store.update({"export_format": "tiff", "export_bit_depth": 8, "export_size": 1024,
                      "export_last_folder": str(tmp_path)})
    assert r["ok"]
    again = st.SettingsStore(tmp_path / "s.json", restrict=lambda p: None)
    assert again.data["export_format"] == "tiff" and again.data["export_bit_depth"] == 8
    assert again.data["export_size"] == 1024
    assert again.data["export_last_folder"] == os.path.abspath(str(tmp_path))
    (tmp_path / "s.json").write_text('{"export_quality": 3, "export_format": 7}', encoding="utf-8")
    broken = st.SettingsStore(tmp_path / "s.json", restrict=lambda p: None)
    assert broken.data["export_quality"] == 92 and broken.data["export_format"] == "jpeg"


def test_app_version():
    assert st.APP_VERSION == "0.17.2"


# ---------------------------------------------------------------- 服务：对话框状态
def test_dialog_state_states(svc):
    s = svc.dialog_state()
    assert s["photo"]["name"] == "DSC00001.ARW" and not s["can_export"] and "保存位置" in s["reason"]
    assert svc.set_folder(str(svc.out))["ok"]
    s = svc.dialog_state()
    assert s["can_export"] and s["folder"] == os.path.abspath(str(svc.out)) and s["options"]["format"] == "jpeg"
    svc.lr_.photo = None
    s = svc.dialog_state()
    assert not s["can_export"] and "没有选中照片" in s["reason"]
    svc.lr_.connected = False
    s = svc.dialog_state()
    assert not s["can_export"] and "未连接" in s["reason"]


def test_remembered_folder_must_still_exist(svc):
    assert svc.set_folder(str(svc.out))["ok"]
    assert svc.settings.data["export_last_folder"] == os.path.abspath(str(svc.out))
    s2 = es.ExportService(svc.settings, svc.lr_, lambda e: None)          # 模拟重启软件：从设置取默认文件夹
    assert s2.dialog_state()["folder"] == os.path.abspath(str(svc.out))
    svc.out.rmdir()
    s3 = es.ExportService(svc.settings, svc.lr_, lambda e: None)
    d = s3.dialog_state()
    assert d["folder"] == "" and "重新选择" in d["folder_message"] and not d["can_export"]


def test_set_folder_rejects_bad(svc, tmp_path):
    r = svc.set_folder(str(tmp_path / "nope"))
    assert not r["ok"] and svc.folder == ""
    assert not svc.set_folder("C:\\Windows")["ok"]


# ---------------------------------------------------------------- 服务：导出
def test_export_success(svc):
    svc.set_folder(str(svc.out))
    svc.dialog_state()
    r = svc.export({**GOOD, "format": "tiff", "bit_depth": 8})
    assert r["ok"]
    assert wait(lambda: svc.state()["stage"] == "done")
    res = svc.state()["result"]
    assert res["status"] == "exported" and res["file"] == "DSC00001_LrMCP_1024px.tif" and res["bytes"] == 2048
    assert res["dimensions"] == "1024 × 683" and res["format_label"] == "TIFF" and "path" not in res
    c = svc.lr_.calls[0]
    assert c["fmt"] == "tiff" and c["bit_depth"] == 8 and c["long_edge"] == 1024 and c["photo"] == "P1"
    assert svc.events[-1]["type"] == "export_done" and svc.events[-1]["status"] == "exported"
    assert svc.settings.data["export_format"] == "tiff" and svc.settings.data["export_bit_depth"] == 8
    assert svc.close()["ok"] and svc.state()["stage"] == "idle"


def test_export_refusals(svc):
    r = svc.export(GOOD)
    assert not r["ok"] and "保存位置" in r["message"] and not svc.lr_.calls
    svc.set_folder(str(svc.out))
    assert not svc.export({**GOOD, "size": 99})["ok"]
    svc.lr_.photo = None
    r = svc.export(GOOD)
    assert not r["ok"] and "没有选中照片" in r["message"]
    svc.lr_.connected = False
    r = svc.export(GOOD)
    assert not r["ok"] and "未连接" in r["message"]
    assert svc.lr_.calls == []


def test_export_photo_changed_since_dialog(svc):
    svc.set_folder(str(svc.out))
    svc.dialog_state()
    svc.lr_.photo = ("P2", "OTHER.ARW")
    r = svc.export(GOOD)
    assert not r["ok"] and r.get("changed") and not svc.lr_.calls


def test_export_folder_removed_before_export(svc):
    svc.set_folder(str(svc.out))
    svc.out.rmdir()
    r = svc.export(GOOD)
    assert not r["ok"] and "重新选择" in r["message"] and not svc.lr_.calls


def test_export_failures_use_server_message(svc):
    class EditError(Exception):
        pass

    class PluginNotConnected(Exception):
        pass

    svc.set_folder(str(svc.out))
    svc.lr_.error = EditError("导出文件夹要是本机文件夹的完整路径。")
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    res = svc.state()["result"]
    assert res["status"] == "failed" and res["message"] == "导出文件夹要是本机文件夹的完整路径。"
    svc.close()
    svc.lr_.error = PluginNotConnected("x")
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    assert "插件未连接" in svc.state()["result"]["message"]
    svc.close()
    svc.lr_.error = RuntimeError("boom")
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    assert svc.state()["result"]["message"].startswith("导出失败")


def test_export_uncertain_from_server(svc):
    svc.set_folder(str(svc.out))
    svc.lr_.uncertain = True
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    res = svc.state()["result"]
    assert res["status"] == "uncertain" and "确认" in res["message"]
    assert svc.reveal_last()["ok"] is False


def test_export_timeout_is_uncertain(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    lr = FakeLr()
    lr.delay = 0.6
    s = es.ExportService(Settings(), lr, lambda e: None, timeout=0.1)
    s.set_folder(str(out))
    assert s.export(GOOD)["ok"]
    assert s.export(GOOD) == {"ok": False, "message": "正在导出，请等待完成。"}      # 进行中不能重复
    assert wait(lambda: s.state()["stage"] == "done")
    assert s.state()["result"]["status"] == "uncertain"
    assert s.last_file == ""


def test_result_file_missing_or_outside_is_failure(svc, tmp_path):
    svc.set_folder(str(svc.out))
    svc.lr_.write = False
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    assert svc.state()["result"]["status"] == "failed"
    svc.close()
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "a.jpg").write_bytes(b"x")
    svc.lr_.write = True
    orig = svc.lr_.export_photo
    svc.lr_.export_photo = lambda *a, **k: {**orig(*a, **k), "path": str(other / "a.jpg")}
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    assert svc.state()["result"]["status"] == "failed" and svc.last_file == ""


def test_reveal_only_last_export_file(svc):
    assert svc.reveal_last()["ok"] is False and svc.revealed == []
    svc.set_folder(str(svc.out))
    svc.export(GOOD)
    assert wait(lambda: svc.state()["stage"] == "done")
    r = svc.reveal_last()
    assert r["ok"] and svc.revealed == [os.path.join(os.path.abspath(str(svc.out)), "DSC00001_LrMCP_1024px.jpg")]
    os.remove(svc.revealed[0])
    assert svc.reveal_last()["ok"] is False
    assert list(inspect.signature(svc.reveal_last).parameters) == []


# ---------------------------------------------------------------- Api 接口
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    lr = FakeLr()
    a._export.lr = lr
    a.fake = lr
    yield a
    a._shutdown()


class FakeWindow:
    def __init__(self, result):
        self.result, self.asked = result, 0

    def create_file_dialog(self, *a, **k):
        self.asked += 1
        return self.result


def test_api_signatures_take_no_paths(api):
    assert list(inspect.signature(api.choose_export_folder).parameters) == []
    assert list(inspect.signature(api.reveal_last_export).parameters) == []
    assert list(inspect.signature(api.export_current_photo).parameters) == ["options"]
    for n in ("export_dialog_state", "export_state", "export_close"):
        assert list(inspect.signature(getattr(api, n)).parameters) == []


def test_api_export_ignores_page_path(api, tmp_path):
    good, evil = tmp_path / "good", tmp_path / "evil"
    good.mkdir()
    evil.mkdir()
    api._window = FakeWindow([str(good)])
    r = api.choose_export_folder()
    assert r["ok"] and r["folder"] == os.path.abspath(str(good))
    assert api.export_dialog_state()["can_export"]
    res = api.export_current_photo({**GOOD, "folder": str(evil), "path": str(evil), "dir": str(evil)})
    assert res["ok"]
    assert wait(lambda: api.export_state()["stage"] == "done")
    assert api.fake.calls[0]["folder"] == os.path.abspath(str(good))
    assert not list(evil.iterdir())
    assert api.export_state()["result"]["status"] == "exported"
    assert api.export_close()["ok"]


def test_api_export_without_folder_and_cancelled_dialog(api):
    api._window = FakeWindow(None)
    r = api.choose_export_folder()
    assert not r["ok"] and r.get("cancelled")
    res = api.export_current_photo(GOOD)
    assert not res["ok"] and "保存位置" in res["message"]
    api._window = None
    assert not api.choose_export_folder()["ok"]


def test_api_bad_folder_from_dialog_rejected(api):
    api._window = FakeWindow([os.environ.get("SystemRoot", "C:\\Windows")])
    r = api.choose_export_folder()
    assert not r["ok"] and r["message"]
    assert not api.export_current_photo(GOOD)["ok"]


def test_export_not_blocked_by_readonly():
    """导出不改照片：后端不检查只读开关。"""
    assert "readonly" not in inspect.getsource(es).lower().replace("只读开关", "")
