"""导入流程编排（ImportService）与 Api 接口：假设置、假 Lightroom、假窗口，临时目录。"""
import os
import subprocess
import time
from pathlib import Path

import pytest

import import_service as isv
import importer as imp
import settings as st


@pytest.fixture(autouse=True)
def tmp_ok(monkeypatch):
    """临时目录在 AppData 里；该规则本身在 test_importer.py 里测。"""
    monkeypatch.setattr(imp, "BLOCKED_PARTS", tuple(b for b in imp.BLOCKED_PARTS if b != "/appdata/"))


class Settings:
    def __init__(self, base):
        self.data = {"base_folder": str(base)}


class FakeLr:
    def __init__(self, connected=True, readonly=None):
        self.connected = connected
        self.readonly = readonly
        self.calls = []
        self.known = set()

    def readonly_error(self):
        return self.readonly

    def import_photo(self, path):
        self.calls.append(path)
        if path.lower() in self.known:
            return {"status": "already"}
        self.known.add(path.lower())
        return {"status": "imported"}


def make(p: Path, size=10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def env(tmp_path):
    card = tmp_path / "card"
    make(card / "DCIM" / "A.ARW", 40)
    make(card / "DCIM" / "B.JPG", 25)
    make(card / "DCIM" / "C.HEIC", 5)
    make(card / "readme.txt", 5)
    base = tmp_path / "lib"
    base.mkdir()
    events = []
    lr = FakeLr()
    svc = isv.ImportService(Settings(base), lr, events.append, data_dir=tmp_path / "LrMcp", sleep=lambda s: None)
    return svc, lr, events, card, base


def scan(svc, card):
    r = svc.set_source(str(card))
    assert r["ok"], r
    assert wait(lambda: svc.stage == "ready")


# ---------------------------------------------------------------- 扫描与确认信息
def test_scan_then_prepare_summary(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    p = svc.prepare("")
    f = p["found"]
    assert p["can_start"] and (f["n"], f["raw"], f["jpeg"], f["other"], f["total_size"]) == (3, 1, 1, 1, 70)
    assert p["target"] == str(base) and p["base_exists"] and p["free"] and p["free_text"] != "未知"
    assert any(e.get("type") == "import_scan" and e.get("state") == "done" for e in events)
    assert not any("files" in e for e in events)                       # 文件清单只留在后台，不推给页面


def test_prepare_category_rules(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    ok = svc.prepare("雪山")
    assert ok["can_start"] and ok["target"] == str(base / "雪山")
    for bad in ("a/b", "..", "x\\y", "C:\\x"):
        r = svc.prepare(bad)
        assert not r["can_start"] and "category" in r["errors"]


def test_prepare_blocks_overlapping_folders(env):
    svc, lr, events, card, base = env
    svc.settings.data["base_folder"] = str(card / "DCIM")          # 软件文件夹在来源之内
    scan(svc, card)
    r = svc.prepare("")
    assert not r["can_start"] and "互相包含" in r["errors"]["base"]
    svc.settings.data["base_folder"] = str(card)                   # 相同
    assert not svc.prepare("")["can_start"]
    svc.settings.data["base_folder"] = str(card.parent)            # 来源在软件文件夹之内
    assert not svc.prepare("")["can_start"]


def test_prepare_blocks_system_and_data_dirs(env, tmp_path):
    svc, lr, events, card, base = env
    scan(svc, card)
    svc.settings.data["base_folder"] = r"C:\Windows\x"
    assert "base" in svc.prepare("")["errors"]
    svc.settings.data["base_folder"] = str(tmp_path / "LrMcp" / "lib")
    r = svc.prepare("")
    assert not r["can_start"] and "数据目录" in r["errors"]["base"]


def test_prepare_insufficient_space(env):
    svc, lr, events, card, base = env
    svc._free = lambda p: 50
    scan(svc, card)
    r = svc.prepare("")
    assert not r["can_start"] and "还差" in r["errors"]["space"] and r["shortfall"] > 0
    assert svc.start("")["ok"] is False


def test_prepare_space_unknown_blocks(env):
    svc, lr, events, card, base = env
    svc._free = lambda p: None
    scan(svc, card)
    assert not svc.prepare("")["can_start"]


def test_prepare_empty_and_truncated(env, tmp_path):
    svc, lr, events, card, base = env
    empty = tmp_path / "empty"
    empty.mkdir()
    scan(svc, empty)
    assert not svc.prepare("")["can_start"] and "没有找到照片" in svc.prepare("")["errors"]["count"]
    svc.close()
    svc._scan_fn = lambda p, **k: imp.scan_folder(p, max_files=2, **{kk: v for kk, v in k.items()})
    scan(svc, card)
    r = svc.prepare("")
    assert not r["can_start"] and "分批" in r["errors"]["count"]


def test_prepare_without_scan(env):
    assert not env[0].prepare("")["can_start"]


def test_unset_base_blocks_import(env):
    svc = env[0]
    svc.settings.data["base_folder"] = st.default_base_folder()
    scan(svc, env[3])
    r = svc.prepare("")
    assert not r["can_start"] and r["base"] == "" and "base" in r["errors"]
    assert not svc.library()["exists"]


def test_scan_cancel(env):
    svc, lr, events, card, base = env
    gate = []

    def slow(p, should_cancel=lambda: False, progress=None):
        while not should_cancel():
            time.sleep(0.01)
        return imp.scan_folder(p, should_cancel=should_cancel)
    svc._scan_fn = slow
    assert svc.set_source(str(card))["ok"]
    assert svc.cancel()["ok"]
    assert wait(lambda: any(e.get("state") == "cancelled" for e in events))
    assert svc.stage == "idle"


def test_set_source_rejects_non_dir(env, tmp_path):
    svc = env[0]
    assert not svc.set_source(str(tmp_path / "nope"))["ok"]
    assert not svc.set_source("")["ok"]


# ---------------------------------------------------------------- 开始导入
def test_full_import_copy_and_register(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in card.rglob("*") if p.is_file()}
    assert svc.start("雪山")["ok"]
    assert wait(lambda: svc.stage == "done")
    res = svc.state()["result"]
    assert res["counts"]["copied"] == 3 and res["counts"]["lr_ok"] == 3 and res["problems"] == []
    assert sorted(p.name for p in (base / "雪山").iterdir()) == ["A.ARW", "B.JPG", "C.HEIC"]
    assert all(str(base / "雪山") in c for c in lr.calls)
    after = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in card.rglob("*") if p.is_file()}
    assert before == after                                              # 原片丝毫未变
    assert [e["type"] for e in events if e["type"].startswith("import")][-1] == "import_done"


def test_flat_import_when_category_blank(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    assert svc.start("")["ok"] and wait(lambda: svc.stage == "done")
    assert sorted(p.name for p in base.iterdir()) == ["A.ARW", "B.JPG", "C.HEIC"]


def test_rerun_skips_and_already(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    svc.start("")
    wait(lambda: svc.stage == "done")
    svc.close()
    scan(svc, card)
    svc.start("")
    wait(lambda: svc.stage == "done")
    c = svc.state()["result"]["counts"]
    assert c["skipped"] == 3 and c["copied"] == 0 and c["lr_ok"] == 3
    assert len(list(base.iterdir())) == 3


def test_readonly_blocks_before_anything(env):
    svc, lr, events, card, base = env
    lr.readonly = "只读模式已开启"
    assert not svc.begin()["ok"] and "只读" in svc.begin()["message"]
    r = svc.set_source(str(card))
    assert not r["ok"] and "只读" in r["message"] and svc.stage == "idle"
    lr.readonly = None
    scan(svc, card)
    lr.readonly = "只读模式已开启"                                      # 扫描后才打开：开始时再次拒绝
    r = svc.start("")
    assert not r["ok"] and "只读" in r["message"] and not list(base.iterdir())


def test_not_connected_copies_only_then_retry(env):
    svc, lr, events, card, base = env
    lr.connected = False
    scan(svc, card)
    assert svc.start("")["ok"] and wait(lambda: svc.stage == "done")
    res = svc.state()["result"]
    assert res["counts"]["copied"] == 3 and res["counts"]["lr_pending"] == 3 and res["pending_retry"] == 3 and lr.calls == []
    assert not svc.retry_lr()["ok"]                                    # 仍未连接
    lr.connected = True
    assert svc.retry_lr()["ok"] and wait(lambda: svc.stage == "done")
    res = svc.state()["result"]
    assert res["counts"]["lr_ok"] == 3 and res["counts"]["copied"] == 3 and res["pending_retry"] == 0 and res.get("retried")
    assert len(lr.calls) == 3
    assert not svc.retry_lr()["ok"]                                    # 没有可重试的了


def test_start_creates_missing_base_only_after_consent(env, tmp_path):
    svc, lr, events, card, base = env
    new = tmp_path / "newlib"
    svc.settings.data["base_folder"] = str(new)
    scan(svc, card)
    r = svc.start("")
    assert not r["ok"] and r["needs_create"] and not new.exists()
    assert svc.start("", create_base=True)["ok"] and wait(lambda: svc.stage == "done")
    assert len(list(new.iterdir())) == 3


def test_start_without_scan_and_double_start(env):
    svc, lr, events, card, base = env
    assert not svc.start("")["ok"]
    scan(svc, card)
    assert svc.start("")["ok"]
    assert not svc.start("")["ok"]                                     # 已在复制或已结束，不能再开
    wait(lambda: svc.stage == "done")


def test_begin_refused_while_copying(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    svc.stage = "copying"
    assert not svc.begin()["ok"]


def test_cancel_during_copy_keeps_finished(env):
    svc, lr, events, card, base = env
    scan(svc, card)
    orig = lr.import_photo

    def slow(path):
        r = orig(path)
        svc.cancel()                                                    # 第一个处理完就取消
        return r
    lr.import_photo = slow
    assert svc.start("")["ok"] and wait(lambda: svc.stage == "done")
    res = svc.state()["result"]
    assert res["cancelled"] and res["counts"]["copied"] == 1
    assert len(list(base.iterdir())) == 1 and not list(base.glob("*.part*"))


def test_category_cannot_escape_base_via_junction(env, tmp_path):
    if os.name != "nt":
        pytest.skip("联接点仅 Windows")
    svc, lr, events, card, base = env
    outside = tmp_path / "outside"
    outside.mkdir()
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(base / "evil"), str(outside)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("无法创建联接点")
    scan(svc, card)
    res = svc.start("evil")
    assert not res["ok"] and "不在软件文件夹" in res["message"] and list(outside.iterdir()) == []


def test_library_listing(env):
    svc, lr, events, card, base = env
    make(base / "雪山" / "a.ARW")
    make(base / "b.jpg")
    t = svc.library(10)
    assert t["total"] == 2 and t["base"] == str(base) and {g["name"] for g in t["groups"]} == {"（未分类）", "雪山"}


def test_scan_skips_junction(tmp_path):
    if os.name != "nt":
        pytest.skip("联接点仅 Windows")
    real = tmp_path / "real"
    make(real / "r.jpg")
    src = tmp_path / "card"
    make(src / "own.jpg")
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(src / "junc"), str(real)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("无法创建联接点")
    res = imp.scan_folder(src)
    assert [os.path.basename(p) for p, _ in res["files"]] == ["own.jpg"] and res["skipped_links"] == 1


# ---------------------------------------------------------------- Api 接口
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    a._import.lr = FakeLr()
    a._import.data_dir = tmp_path / "LrMcp"
    yield a
    a._shutdown()


class FakeWindow:
    def __init__(self, result):
        self.result = result
        self.asked = 0

    def create_file_dialog(self, *a, **k):
        self.asked += 1
        return self.result


def test_api_choose_source_folder_flow(api, tmp_path):
    card = tmp_path / "card"
    make(card / "A.ARW", 10)
    lib = tmp_path / "lib"
    lib.mkdir()
    api._settings.data["base_folder"] = str(lib)
    api._window = FakeWindow([str(card)])
    r = api.choose_source_folder()
    assert r["ok"] and r["path"] == str(card)
    assert wait(lambda: api.import_state()["stage"] == "ready")
    assert api.import_prepare("")["can_start"]
    assert api.import_start("2026")["ok"]
    assert wait(lambda: api.import_state()["stage"] == "done")
    assert api.import_state()["result"]["counts"]["lr_ok"] == 1
    assert (lib / "2026" / "A.ARW").exists()
    assert api.import_close()["ok"] and api.import_state()["stage"] == "idle"


def test_api_choose_source_cancelled_and_no_window(api):
    api._window = FakeWindow(None)
    r = api.choose_source_folder()
    assert not r["ok"] and r.get("cancelled")
    api._window = None
    assert not api.choose_source_folder()["ok"]


def test_api_choose_source_readonly_refused_without_dialog(api):
    api._import.lr.readonly = "只读模式已开启"
    w = FakeWindow(["x"])
    api._window = w
    r = api.choose_source_folder()
    assert not r["ok"] and "只读" in r["message"] and w.asked == 0


def test_api_has_no_path_taking_import_entry(api):
    """页面不能传来源路径：choose_source_folder 不接受参数，其余导入接口只接受分类名与开关。"""
    import inspect
    assert list(inspect.signature(api.choose_source_folder).parameters) == []
    for name in ("import_prepare", "import_start", "import_cancel", "import_close", "import_retry_lr", "import_state", "library_list"):
        params = inspect.signature(getattr(api, name)).parameters
        assert not any("path" in p or "folder" in p or "source" in p for p in params)


def test_api_open_library(api, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    api._settings.data["base_folder"] = str(tmp_path / "nolib")
    assert not api.open_library()["ok"] and opened == []
    (tmp_path / "nolib").mkdir()
    assert api.open_library()["ok"] and opened == [str(tmp_path / "nolib")]
    assert list(__import__("inspect").signature(api.open_library).parameters) == []


def test_api_library_list(api, tmp_path):
    lib = tmp_path / "lib"
    make(lib / "雪山" / "a.JPG")
    api._settings.data["base_folder"] = str(lib)
    t = api.library_list()
    assert t["total"] == 1 and t["groups"][0]["name"] == "雪山"
