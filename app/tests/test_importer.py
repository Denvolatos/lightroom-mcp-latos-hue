"""导入：扫描、复制（.part、同名处理、校验）、加入 Lightroom 的重试规则、目录树、各类校验。全部用临时目录与假通道。"""
import os
import subprocess
import sys
import threading

import pytest

import importer as imp


def make(tmp, rel, size=10, data=None):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if data is not None else b"x" * size)
    return p


# ---------------------------------------------------------------- 扫描
def test_scan_counts_recursive_and_filters(tmp_path):
    make(tmp_path, "DCIM/100/A.ARW", 30)
    make(tmp_path, "DCIM/100/A.JPG", 20)
    make(tmp_path, "DCIM/100/b.jpeg", 5)
    make(tmp_path, "DCIM/101/C.HEIC", 7)
    make(tmp_path, "DCIM/101/note.txt", 100)
    make(tmp_path, "DCIM/101/movie.mp4", 100)
    make(tmp_path, "DCIM/101/noext", 100)
    r = imp.scan_folder(tmp_path)
    assert [os.path.basename(p) for p, _ in r["files"]] == ["A.ARW", "A.JPG", "b.jpeg", "C.HEIC"]
    assert r["counts"] == {"raw": 1, "jpeg": 2, "other": 1}
    assert r["total_size"] == 62 and not r["truncated"] and r["error"] == ""


def test_scan_extensions_whitelist_case_insensitive(tmp_path):
    for e in "jpg jpeg arw cr2 cr3 nef nrw raf orf rw2 dng tif tiff heic heif png".split():
        make(tmp_path, f"x.{e.upper()}")
    make(tmp_path, "x.gif")
    make(tmp_path, "x.exe")
    assert len(imp.scan_folder(tmp_path)["files"]) == 16


def test_scan_depth_limit(tmp_path):
    make(tmp_path, "a/b/c/d/e/f/ok.jpg")            # 深度 6：允许
    make(tmp_path, "a/b/c/d/e/f/g/too_deep.jpg")    # 深度 7：不进入
    names = [os.path.basename(p) for p, _ in imp.scan_folder(tmp_path)["files"]]
    assert names == ["ok.jpg"]


def test_scan_skips_hidden_and_system_dirs(tmp_path):
    make(tmp_path, "$RECYCLE.BIN/x.jpg")
    make(tmp_path, "System Volume Information/x.jpg")
    make(tmp_path, ".Trashes/x.jpg")
    make(tmp_path, ".hidden/x.jpg")
    make(tmp_path, "._A.ARW")
    make(tmp_path, "good/g.jpg")
    assert [os.path.basename(p) for p, _ in imp.scan_folder(tmp_path)["files"]] == ["g.jpg"]


@pytest.mark.skipif(os.name != "nt", reason="Windows 文件属性")
def test_scan_skips_windows_hidden_attribute(tmp_path):
    make(tmp_path, "hid/h.jpg")
    make(tmp_path, "vis/v.jpg")
    subprocess.run(["attrib", "+h", str(tmp_path / "hid")], check=True, capture_output=True)
    try:
        assert [os.path.basename(p) for p, _ in imp.scan_folder(tmp_path)["files"]] == ["v.jpg"]
    finally:
        subprocess.run(["attrib", "-h", str(tmp_path / "hid")], capture_output=True)


def test_scan_does_not_follow_symlinks(tmp_path):
    real = tmp_path / "real"
    make(real, "r.jpg")
    src = tmp_path / "card"
    make(src, "own.jpg")
    try:
        os.symlink(real, src / "linkdir", target_is_directory=True)
        os.symlink(real / "r.jpg", src / "linkfile.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("本机不能创建符号链接")
    r = imp.scan_folder(src)
    assert [os.path.basename(p) for p, _ in r["files"]] == ["own.jpg"] and r["skipped_links"] == 2


def test_scan_limit_truncates(tmp_path):
    for i in range(12):
        make(tmp_path, f"p{i:02d}.jpg")
    r = imp.scan_folder(tmp_path, max_files=10)
    assert r["truncated"] and len(r["files"]) == 10


def test_scan_cancel_and_bad_root(tmp_path):
    make(tmp_path, "a.jpg")
    assert imp.scan_folder(tmp_path, should_cancel=lambda: True)["cancelled"]
    assert imp.scan_folder(tmp_path / "nope")["error"]


def test_scan_never_modifies(tmp_path):
    p = make(tmp_path, "a.jpg", 5)
    before = (p.stat().st_size, p.stat().st_mtime_ns)
    imp.scan_folder(tmp_path)
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before


# ---------------------------------------------------------------- 复制
def test_copy_basic_preserves_source_and_time(tmp_path):
    src = make(tmp_path, "card/A.ARW", data=b"abc" * 1000)
    os.utime(src, (1_700_000_000, 1_700_000_000))
    lib = tmp_path / "lib"
    lib.mkdir()
    before = (src.stat().st_size, src.stat().st_mtime_ns)
    r = imp.copy_one(src, lib)
    assert r["status"] == "copied" and (lib / "A.ARW").read_bytes() == src.read_bytes()
    assert (src.stat().st_size, src.stat().st_mtime_ns) == before and src.exists()
    assert (lib / "A.ARW").stat().st_mtime == 1_700_000_000
    assert not list(lib.glob("*.part*"))


def test_copy_skips_same_name_same_size(tmp_path):
    src = make(tmp_path, "card/A.jpg", data=b"1234")
    lib = tmp_path / "lib"
    make(lib, "A.jpg", data=b"abcd")                   # 同名同大小（内容不同也视为已导入）
    r = imp.copy_one(src, lib)
    assert r["status"] == "skipped" and (lib / "A.jpg").read_bytes() == b"abcd"
    assert sorted(p.name for p in lib.iterdir()) == ["A.jpg"]


def test_copy_renames_when_size_differs_never_overwrites(tmp_path):
    src = make(tmp_path, "card/A.jpg", data=b"1234")
    lib = tmp_path / "lib"
    make(lib, "A.jpg", data=b"longer-content")
    r = imp.copy_one(src, lib)
    assert r["status"] == "copied" and r["dest"].endswith("A_2.jpg")
    assert (lib / "A.jpg").read_bytes() == b"longer-content" and (lib / "A_2.jpg").read_bytes() == b"1234"
    make(lib, "A_3.jpg", data=b"zz")
    src2 = make(tmp_path, "card2/A.jpg", data=b"12345678901")        # 又一个不同大小的同名文件 -> _4
    r2 = imp.copy_one(src2, lib)
    assert r2["dest"].endswith("A_4.jpg")


def test_copy_second_run_is_skipped_via_renamed_copy(tmp_path):
    src = make(tmp_path, "card/A.jpg", data=b"1234")
    lib = tmp_path / "lib"
    make(lib, "A.jpg", data=b"longer-content")
    assert imp.copy_one(src, lib)["status"] == "copied"       # -> A_2.jpg
    again = imp.copy_one(src, lib)
    assert again["status"] == "skipped" and again["dest"].endswith("A_2.jpg")


def test_copy_failure_cleans_only_own_part(tmp_path, monkeypatch):
    src = make(tmp_path, "card/A.jpg", data=b"1234567890")
    lib = tmp_path / "lib"
    lib.mkdir()
    foreign = make(lib, "A.jpg.part", data=b"foreign")        # 别人的 .part：不能动
    real_rename = os.rename

    def boom(a, b):
        raise OSError(5, "模拟失败")
    monkeypatch.setattr(os, "rename", boom)
    r = imp.copy_one(src, lib)
    monkeypatch.setattr(os, "rename", real_rename)
    assert r["status"] == "failed"
    assert foreign.read_bytes() == b"foreign"                 # 没被删除或覆盖
    assert sorted(p.name for p in lib.iterdir()) == ["A.jpg.part"]    # 自己的 .part2 已清理，也没有正式文件
    assert src.read_bytes() == b"1234567890"


def test_copy_size_mismatch_detected(tmp_path, monkeypatch):
    src = make(tmp_path, "card/A.jpg", data=b"x" * 100)
    lib = tmp_path / "lib"
    lib.mkdir()
    real_open = open

    def short_write(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        if "xb" in mode:
            orig = f.write
            f.write = lambda b: orig(b[: len(b) // 2])          # 少写一半，模拟校验失败
        return f
    monkeypatch.setattr("builtins.open", short_write)
    r = imp.copy_one(src, lib)
    monkeypatch.undo()
    assert r["status"] == "failed" and "不一致" in r["reason"]
    assert list(lib.iterdir()) == []                              # .part 已清理，没有正式文件
    assert src.read_bytes() == b"x" * 100


def test_copy_source_changed_during_copy_fails(tmp_path, monkeypatch):
    src = make(tmp_path, "card/A.jpg", data=b"x" * 100)
    lib = tmp_path / "lib"
    lib.mkdir()
    real_utime = os.utime

    def touch_then(path, *a, **k):
        return real_utime(path, *a, **k)
    # 在读完之后、核对之前改动原文件的修改时间（只在测试里改自己的临时文件）
    real_stat_size = os.path.getsize
    orig_open = open

    def open_and_touch(file, mode="r", *a, **k):
        f = orig_open(file, mode, *a, **k)
        if mode == "rb" and str(file) == str(src):
            real_utime(src, ns=(1, 1))
        return f
    monkeypatch.setattr("builtins.open", open_and_touch)
    r = imp.copy_one(src, lib)
    monkeypatch.undo()
    assert r["status"] == "failed" and list(lib.iterdir()) == []


def test_copy_rejects_non_regular_and_missing(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    assert imp.copy_one(tmp_path / "nope.jpg", lib)["status"] == "failed"
    d = tmp_path / "dir.jpg"
    d.mkdir()
    assert imp.copy_one(d, lib)["status"] == "failed"
    try:
        target = make(tmp_path, "t.jpg")
        os.symlink(target, tmp_path / "lnk.jpg")
    except (OSError, NotImplementedError):
        return
    r = imp.copy_one(tmp_path / "lnk.jpg", lib)
    assert r["status"] == "failed" and "链接" in r["reason"]


def test_copy_free_space_check(tmp_path):
    src = make(tmp_path, "card/A.jpg", data=b"x" * 1000)
    lib = tmp_path / "lib"
    lib.mkdir()
    r = imp.copy_one(src, lib, free_check=lambda: 10)
    assert r["status"] == "failed" and "空间不足" in r["reason"] and list(lib.iterdir()) == []


# ---------------------------------------------------------------- 校验
@pytest.mark.parametrize("name", ["", None, "  ", "雪山", "2026-11 旅行", "a b"])
def test_category_ok(name):
    assert imp.validate_category(name)[0]


@pytest.mark.parametrize("name", ["a/b", "a\\b", "..", "a..b", "../x", "C:x", "a*b", "a?b", "a|b", "a<b", '"a', ".hid", "dot.",
                                  "CON", "nul.txt", "x" * 61, "a\x01b", 5])
def test_category_bad(name):
    assert not imp.validate_category(name)[0]


def test_category_strips_blanks():
    assert imp.validate_category("  雪山 ") == (True, "雪山", "")
    assert imp.validate_category("")[1] == ""


@pytest.fixture
def tmp_ok(monkeypatch):
    """pytest 的临时目录在 AppData 里，会被“软件文件夹不能在 AppData”规则拒绝；关系测试里去掉该项（该规则另有测试）。"""
    monkeypatch.setattr(imp, "BLOCKED_PARTS", tuple(b for b in imp.BLOCKED_PARTS if b != "/appdata/"))


def test_appdata_is_blocked_for_base(tmp_path):
    assert "/appdata/" in imp.BLOCKED_PARTS and not imp.check_folders(str(tmp_path / "card"), r"C:\Users\u\AppData\x")[0]


def test_folder_relation(tmp_path, tmp_ok):
    a = tmp_path / "card"
    b = tmp_path / "lib"
    a.mkdir(); b.mkdir()
    assert imp.check_folders(str(a), str(b))[0]
    assert not imp.check_folders(str(a), str(a))[0]
    assert not imp.check_folders(str(a), str(a / "lib"))[0]            # 软件文件夹在来源里
    assert not imp.check_folders(str(b / "card"), str(b))[0]           # 来源在软件文件夹里
    assert imp.check_folders(str(tmp_path / "card2"), str(tmp_path / "card"))[0]   # 前缀相同但不是包含


def test_folder_relation_data_dir_and_blocked(tmp_path, tmp_ok):
    data = tmp_path / "LrMcp"
    data.mkdir()
    ok = tmp_path / "card"
    assert not imp.check_folders(str(ok), str(data / "x"), data)[0]
    assert not imp.check_folders(str(data / "x"), str(tmp_path / "lib"), data)[0]
    assert not imp.check_folders(str(ok), str(tmp_path), data)[0]       # 软件文件夹包含数据目录
    assert not imp.check_folders(str(ok), "C:\\Windows\\Temp\\x")[0]
    assert not imp.check_folders("", str(tmp_path))[0]


def test_library_tree(tmp_path):
    make(tmp_path, "root.jpg")
    make(tmp_path, "雪山/a.ARW")
    make(tmp_path, "雪山/b.jpg")
    make(tmp_path, "雪山/c.jpg.part")
    make(tmp_path, "街拍/z.png")
    make(tmp_path, "空/readme.txt")
    t = imp.library_tree(tmp_path)
    assert t["exists"] and t["total"] == 4
    assert [(g["name"], g["count"]) for g in t["groups"]] == [("（未分类）", 1), ("街拍", 1), ("雪山", 2)]
    small = imp.library_tree(tmp_path, limit=2)
    assert small["shown"] == 2 and small["more"] == 2 and small["total"] == 4
    assert imp.library_tree(tmp_path / "x")["exists"] is False


# ---------------------------------------------------------------- 加入 Lightroom
class Boom(Exception):
    pass


def exc(name, msg=""):
    return type(name, (RuntimeError,), {})(msg)


def test_lr_imported_and_already():
    assert imp.add_to_lightroom("p", lambda p: {"status": "imported"})["lr"] == "imported"
    assert imp.add_to_lightroom("p", lambda p: {"status": "already"})["lr"] == "already"


def test_lr_uncertain_not_retried():
    calls = []

    def fn(p):
        calls.append(p)
        return {"status": "uncertain"}
    r = imp.add_to_lightroom("p", fn, sleep=lambda s: None)
    assert r["lr"] == "uncertain" and len(calls) == 1


def test_lr_timeout_exception_is_uncertain_not_retried():
    calls = []

    def fn(p):
        calls.append(1)
        raise exc("BridgeTimeout", "超时")
    r = imp.add_to_lightroom("p", fn, sleep=lambda s: None)
    assert r["lr"] == "uncertain" and len(calls) == 1


def test_lr_busy_retries_then_succeeds_and_gives_up():
    seq = [exc("BridgeError", "Lightroom 现在不能写入（可能正忙）"), exc("BridgeError", "Lightroom 现在不能写入（可能正忙）"), {"status": "imported"}]
    waits = []

    def fn(p):
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v
    assert imp.add_to_lightroom("p", fn, sleep=waits.append)["lr"] == "imported" and len(waits) == 2

    n = []

    def always(p):
        n.append(1)
        raise exc("BridgeError", "Lightroom 现在不能写入（可能正忙）")
    r = imp.add_to_lightroom("p", always, sleep=lambda s: None)
    assert r["lr"] == "failed" and "繁忙" in r["reason"] and len(n) == imp.BUSY_RETRIES + 1


def test_lr_not_connected_readonly_and_refusal():
    assert imp.add_to_lightroom("p", lambda p: (_ for _ in ()).throw(exc("PluginNotConnected")))["lr"] == "pending"
    assert imp.add_to_lightroom("p", lambda p: (_ for _ in ()).throw(exc("ReadOnlyError")))["lr"] == "failed"
    r = imp.add_to_lightroom("p", lambda p: (_ for _ in ()).throw(exc("BridgeError", "不支持的格式")))
    assert r["lr"] == "failed" and "不支持的格式" in r["reason"]


# ---------------------------------------------------------------- 任务编排
class FakeLr:
    def __init__(self, connected=True):
        self.connected = connected
        self.calls = []
        self.known = set()
        self.fail = {}

    def import_photo(self, path):
        self.calls.append(path)
        n = os.path.basename(path)
        if n in self.fail:
            raise self.fail[n]
        if path.lower() in self.known:
            return {"status": "already"}
        self.known.add(path.lower())
        return {"status": "imported"}


def run_job(files, lib, lr=None, **kw):
    events = []
    job = imp.ImportJob(files, lib, import_fn=(lr.import_photo if lr else None), connected=(lambda: lr.connected) if lr else (lambda: False),
                        emit=events.append, sleep=lambda s: None, **kw)
    job.run()
    return job, events


def files_of(tmp_path, specs):
    out = []
    for rel, data in specs:
        p = make(tmp_path, "card/" + rel, data=data)
        out.append((str(p), len(data)))
    return out


def test_job_copy_and_import_all(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30), ("B.JPG", b"b" * 20)])
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr()
    job, ev = run_job(fs, lib, lr)
    c = job.counts()
    assert c["copied"] == 2 and c["lr_ok"] == 2 and c["failed"] == 0
    assert [os.path.basename(p) for p in lr.calls] == ["A.ARW", "B.JPG"]         # 顺序调用，且导入的是副本
    assert all(str(lib) in p for p in lr.calls)
    prog = [e for e in ev if e["type"] == "import_progress"]
    assert [e["i"] for e in prog] == [0, 1] and prog[0]["name"] == "A.ARW" and prog[0]["n"] == 2
    assert ev[-1]["type"] == "import_done" and ev[-1]["counts"]["lr_ok"] == 2 and ev[-1]["problems"] == []


def test_job_rerun_skips_and_lightroom_says_already(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30)])
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr()
    run_job(fs, lib, lr)
    job2, _ = run_job(fs, lib, lr)
    c = job2.counts()
    assert c["skipped"] == 1 and c["copied"] == 0 and c["lr_ok"] == 1
    assert job2.items[0]["lr"] == "already"
    assert sorted(p.name for p in lib.iterdir()) == ["A.ARW"]


def test_job_failed_copy_not_imported_and_listed(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30)]) + [(str(tmp_path / "card" / "gone.jpg"), 5)]
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr()
    job, ev = run_job(fs, lib, lr)
    assert job.counts()["failed"] == 1 and len(lr.calls) == 1
    pr = ev[-1]["problems"]
    assert len(pr) == 1 and pr[0]["name"] == "gone.jpg" and pr[0]["copy"] == "failed" and pr[0]["reason"]


def test_job_uncertain_flagged_and_not_retried(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30), ("B.JPG", b"b" * 20)])
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr()
    lr.fail["A.ARW"] = exc("BridgeTimeout", "超时")
    job, ev = run_job(fs, lib, lr)
    c = job.counts()
    assert c["lr_uncertain"] == 1 and c["lr_ok"] == 1 and lr.calls.count(str(lib / "A.ARW")) == 1
    assert any(p["lr"] == "uncertain" for p in ev[-1]["problems"])


def test_job_not_connected_copies_only_then_retry(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30), ("B.JPG", b"b" * 20)])
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr(connected=False)
    job, ev = run_job(fs, lib, lr)
    assert job.counts()["copied"] == 2 and job.counts()["lr_pending"] == 2 and lr.calls == []
    assert ev[-1]["pending_retry"] == 2
    pending = job.pending_files()
    assert len(pending) == 2
    lr.connected = True
    retry, _ = run_job(pending, lib, lr, mode="retry")
    assert retry.counts()["lr_ok"] == 2 and len(lr.calls) == 2


def test_job_without_import_fn_marks_pending(tmp_path):
    fs = files_of(tmp_path, [("A.ARW", b"a" * 30)])
    lib = tmp_path / "lib"
    lib.mkdir()
    job, _ = run_job(fs, lib, None)
    assert job.items[0]["lr"] == "pending"


def test_job_cancel_stops_after_current_file(tmp_path):
    fs = files_of(tmp_path, [(f"{i}.jpg", b"x" * (10 + i)) for i in range(5)])
    lib = tmp_path / "lib"
    lib.mkdir()
    lr = FakeLr()
    holder = {}
    orig = lr.import_photo

    def import_then_cancel(path):
        r = orig(path)
        if len(lr.calls) == 2:
            holder["job"].cancel()
        return r
    events = []
    job = imp.ImportJob(fs, lib, import_fn=import_then_cancel, connected=lambda: True, emit=events.append, sleep=lambda s: None)
    holder["job"] = job
    job.run()
    assert job.cancelled and job.counts()["copied"] == 2 and len(job.items) == 2
    assert sorted(p.name for p in lib.iterdir()) == ["0.jpg", "1.jpg"]            # 已完成的保留，其余没复制，没有 .part
    assert all(os.path.exists(p) for p, _ in fs)                                           # 原片都在
    assert events[-1]["cancelled"] is True


def test_job_progress_elapsed_uses_clock(tmp_path):
    fs = files_of(tmp_path, [("A.jpg", b"a" * 5)])
    lib = tmp_path / "lib"
    lib.mkdir()
    t = [100.0]

    def clock():
        t[0] += 1.0
        return t[0]
    job, ev = run_job(fs, lib, FakeLr(), clock=clock)
    assert ev[-1]["elapsed"] > 0


def test_job_disk_full_midway_reports_each(tmp_path):
    fs = files_of(tmp_path, [("A.jpg", b"a" * 5), ("B.jpg", b"b" * 5)])
    lib = tmp_path / "lib"
    lib.mkdir()
    n = {"c": 0}

    def free():
        n["c"] += 1
        return 10 ** 9 if n["c"] == 1 else 1                    # 第二个文件时空间不足
    job, _ = run_job(fs, lib, FakeLr(), free_check=free)
    assert job.counts()["copied"] == 1 and job.counts()["failed"] == 1 and "空间不足" in job.items[1]["reason"]
