# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.2.0 照片库导入：按拍摄日期落位、整个库范围的内容去重（含惰性哈希）、重复与复制结果分开计数、取消、空间检查。
全部用 tmp_path 里造的文件与假 Lightroom。"""
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

import capture_date
import import_service as isv
import importer as imp
from test_capture_date import jpeg_with, tiff_with


@pytest.fixture(autouse=True)
def tmp_ok(monkeypatch):
    monkeypatch.setattr(imp, "BLOCKED_PARTS", tuple(b for b in imp.BLOCKED_PARTS if b != "/appdata/"))


class Settings:
    def __init__(self, base):
        self.data = {"base_folder": str(base)}


class FakeLr:
    connected = True

    def __init__(self):
        self.calls = []

    def readonly_error(self):
        return None

    def import_photo(self, path):
        self.calls.append(path)
        return {"status": "imported"}


def make(p: Path, data=b"x" * 10, when=None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else b"x" * data)
    if when is not None:
        ts = datetime(*when).timestamp()
        os.utime(p, (ts, ts))
    return p


def wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def exif_jpeg(day="2026:11:14 09:30:05", pad=b""):
    return jpeg_with(tiff_with(day)) + pad


def mk_service(tmp_path, **kw):
    base = tmp_path / "lib"
    base.mkdir(exist_ok=True)
    events, lr = [], FakeLr()
    svc = isv.ImportService(Settings(base), lr, events.append, data_dir=tmp_path / "LrMcp", sleep=lambda s: None, **kw)
    return svc, lr, events, base


def scan(svc, card):
    assert svc.set_source(str(card))["ok"]
    assert wait(lambda: svc.stage == "ready")


def run_import(svc):
    assert svc.start()["ok"]
    assert wait(lambda: svc.stage == "done")
    return svc.state()["result"]


def files_under(base: Path):
    return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file())


# ---------------------------------------------------------------- 落位：按拍摄日期
def test_exif_capture_date_decides_folder_not_mtime(tmp_path):
    card = tmp_path / "card"
    make(card / "a.jpg", exif_jpeg("2026:11:14 09:30:05"), when=(2020, 1, 1, 0, 0, 0))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    run_import(svc)
    assert files_under(base) == ["2026/2026-11-14/a.jpg"]


def test_mtime_used_when_no_capture_date_and_when_exif_year_is_invalid(tmp_path):
    card = tmp_path / "card"
    make(card / "plain.png", b"\x89PNG\r\n\x1a\n" + b"p" * 20, when=(2024, 2, 29, 23, 59, 0))
    make(card / "zero.jpg", exif_jpeg("0000:00:00 00:00:00"), when=(2023, 7, 8, 1, 2, 3))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    run_import(svc)
    assert files_under(base) == ["2023/2023-07-08/zero.jpg", "2024/2024-02-29/plain.png"]


def test_midnight_is_camera_local_no_timezone_shift(tmp_path):
    card = tmp_path / "card"
    make(card / "late.jpg", exif_jpeg("2026:12:31 23:59:59"))
    make(card / "early.jpg", exif_jpeg("2027:01:01 00:00:00"))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    run_import(svc)
    assert files_under(base) == ["2026/2026-12-31/late.jpg", "2027/2027-01-01/early.jpg"]


def test_existing_old_category_folders_are_left_alone(tmp_path):
    card = tmp_path / "card"
    make(card / "n.jpg", exif_jpeg())
    svc, lr, ev, base = mk_service(tmp_path)
    old = make(base / "雪山" / "old.jpg", b"old")
    flat = make(base / "flat.jpg", b"flat!")
    scan(svc, card)
    run_import(svc)
    assert old.read_bytes() == b"old" and flat.read_bytes() == b"flat!"
    assert files_under(base) == ["2026/2026-11-14/n.jpg", "flat.jpg", "雪山/old.jpg"]


def test_job_without_explicit_folder_computes_its_own_date_folder(tmp_path):
    src = make(tmp_path / "card" / "a.jpg", exif_jpeg("2022:05:06 07:08:09"))
    lib = tmp_path / "lib"
    lib.mkdir()
    job = imp.ImportJob([(str(src), src.stat().st_size)], lib)
    job.run()
    assert job.counts()["copied"] == 1 and files_under(lib) == ["2022/2022-05-06/a.jpg"]


@pytest.mark.parametrize("rel", ["../x", "2026/../../x", "a/b", "2026/2026-11-14/extra", "C:/x", "/abs", "2026\\2026-11-14", " "])
def test_job_rejects_unexpected_relative_folder(tmp_path, rel):
    src = make(tmp_path / "card" / "a.jpg", 10)
    lib = tmp_path / "lib"
    lib.mkdir()
    job = imp.ImportJob([(str(src), 10, rel)], lib)
    job.run()
    assert job.counts()["failed"] == 1 and not any(lib.iterdir()) and src.exists()


def test_job_creates_folder_with_exist_ok_when_two_files_share_a_day(tmp_path):
    a = make(tmp_path / "card" / "a.jpg", exif_jpeg("2026:11:14 01:00:00"))
    b = make(tmp_path / "card" / "b.jpg", exif_jpeg("2026:11:14 02:00:00", pad=b"zz"))
    lib = tmp_path / "lib"
    lib.mkdir()
    job = imp.ImportJob([(str(a), a.stat().st_size, "2026/2026-11-14"), (str(b), b.stat().st_size, "2026/2026-11-14")], lib)
    job.run()
    assert job.counts()["copied"] == 2 and files_under(lib) == ["2026/2026-11-14/a.jpg", "2026/2026-11-14/b.jpg"]


# ---------------------------------------------------------------- 去重
def test_duplicate_in_other_date_folder_with_different_name_is_skipped(tmp_path):
    card = tmp_path / "card"
    content = exif_jpeg("2026:11:14 09:30:05")
    make(card / "DSC0001.jpg", content)
    make(card / "fresh.jpg", exif_jpeg("2026:11:15 10:00:00"))
    svc, lr, ev, base = mk_service(tmp_path)
    existing = make(base / "2019" / "2019-03-03" / "renamed_long_ago.jpg", content)     # 库里别的日期文件夹、不同文件名
    scan(svc, card)
    p = svc.prepare()
    assert p["duplicates"] == {"count": 1, "size": len(content), "size_text": imp.fmt_size(len(content)), "in_library": 1, "in_batch": 0}
    assert p["to_copy"]["count"] == 1 and [d["day"] for d in p["date_summary"]] == ["2026-11-15"]
    res = run_import(svc)
    assert files_under(base) == ["2019/2019-03-03/renamed_long_ago.jpg", "2026/2026-11-15/fresh.jpg"]
    assert existing.read_bytes() == content
    assert res["counts"]["duplicate"] == 1 and res["counts"]["copied"] == 1 and res["counts"]["skipped"] == 0
    assert res["duplicates"]["in_library"] == 1 and res["n"] == 1
    assert [os.path.basename(c) for c in lr.calls] == ["fresh.jpg"]                 # 重复的没有再加入 Lightroom


def test_same_size_different_content_is_not_a_duplicate(tmp_path):
    card = tmp_path / "card"
    make(card / "a.png", b"A" * 100, when=(2026, 1, 1, 0, 0, 0))
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "x" / "other.png", b"B" * 100)
    scan(svc, card)
    p = svc.prepare()
    assert p["duplicates"]["count"] == 0 and p["to_copy"]["count"] == 1
    run_import(svc)
    assert (base / "2026" / "2026-01-01" / "a.png").read_bytes() == b"A" * 100


def test_hash_is_lazy_only_same_size_files_are_hashed(tmp_path, monkeypatch):
    card = tmp_path / "card"
    make(card / "u1.png", b"1" * 11)
    make(card / "u2.png", b"2" * 22)
    make(card / "same.png", b"3" * 33)
    base = tmp_path / "lib"
    make(base / "q" / "q.png", b"3" * 33)
    make(base / "q" / "other_size.png", b"9" * 44)
    hashed = []
    real = imp.hash_file
    monkeypatch.setattr(imp, "hash_file", lambda p, c=lambda: False: hashed.append(os.path.basename(str(p))) or real(p, c))
    scan_res = imp.scan_folder(card)
    plan = imp.plan_import(scan_res["files"], base)
    assert sorted(hashed) == ["q.png", "same.png"]
    assert {os.path.basename(i["src"]): i["status"] for i in plan["items"]} == {"u1.png": "copy", "u2.png": "copy", "same.png": "dup_library"}


def test_duplicates_within_the_same_import_are_copied_once(tmp_path):
    card = tmp_path / "card"
    content = exif_jpeg("2026:11:14 09:30:05")
    make(card / "100" / "A.jpg", content)
    make(card / "101" / "B.jpg", content)           # 同批重复，名字不同
    make(card / "102" / "A.jpg", content)           # 同批重复，名字相同
    make(card / "103" / "C.jpg", exif_jpeg("2026:11:14 09:30:06"))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    p = svc.prepare()
    assert p["duplicates"]["in_batch"] == 2 and p["duplicates"]["in_library"] == 0 and p["to_copy"]["count"] == 2
    res = run_import(svc)
    assert files_under(base) == ["2026/2026-11-14/A.jpg", "2026/2026-11-14/C.jpg"]
    assert res["counts"]["duplicate"] == 2 and res["counts"]["copied"] == 2
    assert res["duplicates"]["in_batch"] == 2


def test_same_name_different_content_is_renamed_not_skipped(tmp_path):
    card = tmp_path / "card"
    c1, c2 = exif_jpeg("2026:11:14 09:30:05"), exif_jpeg("2026:11:14 09:30:05", pad=b"zz")
    make(card / "100" / "IMG_1.jpg", c1)
    make(card / "101" / "IMG_1.jpg", c2)
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    res = run_import(svc)
    assert files_under(base) == ["2026/2026-11-14/IMG_1.jpg", "2026/2026-11-14/IMG_1_2.jpg"]
    assert res["counts"]["copied"] == 2 and res["counts"]["duplicate"] == 0
    assert {(base / f).read_bytes() for f in files_under(base)} == {c1, c2}


def test_same_name_same_content_in_the_target_day_is_a_library_duplicate(tmp_path):
    card = tmp_path / "card"
    c = exif_jpeg()
    make(card / "IMG_1.jpg", c)
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "2026" / "2026-11-14" / "IMG_1.jpg", c)
    scan(svc, card)
    p = svc.prepare()
    assert not p["can_start"] and "all_duplicate" in p["errors"] and p["duplicates"]["in_library"] == 1


def test_originals_untouched_by_dedup_and_copy(tmp_path):
    card = tmp_path / "card"
    c = exif_jpeg()
    a = make(card / "a.jpg", c, when=(2026, 5, 5, 5, 5, 5))
    b = make(card / "b.jpg", c, when=(2026, 5, 5, 5, 5, 5))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (a, b)}
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    run_import(svc)
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (a, b)} == before


def test_library_scan_ignores_links_hidden_and_non_photos(tmp_path):
    base = tmp_path / "lib"
    make(base / "a" / "p.jpg", b"1" * 5)
    make(base / "a" / "p.jpg.part", b"2" * 6)
    make(base / "a" / "notes.txt", b"3" * 7)
    make(base / ".hidden" / "h.jpg", b"4" * 8)
    make(base / "$RECYCLE.BIN" / "r.jpg", b"5" * 9)
    sizes = imp.library_sizes(base)
    assert sizes == {5: [str(base / "a" / "p.jpg")]}
    assert imp.library_sizes(tmp_path / "missing") == {}


def test_library_scan_goes_deep(tmp_path):
    base = tmp_path / "lib"
    deep = make(base / "a" / "b" / "c" / "d" / "e" / "x.jpg", b"1" * 5)
    assert imp.library_sizes(base) == {5: [str(deep)]}


# ---------------------------------------------------------------- 摘要
def test_date_summary_is_sorted_capped_at_30_and_rest_merged(tmp_path):
    items = []
    for i in range(35):
        d = datetime(2026, 1, 1).toordinal() + i
        day = datetime.fromordinal(d)
        for k in range(1 + i % 2):
            items.append({"src": f"s{i}_{k}", "size": 10, "rel": f"{day:%Y}/{day:%Y-%m-%d}", "status": "copy", "dup_of": ""})
    s = imp.summarize_plan(items)
    assert len(s["date_summary"]) == 30 and s["date_summary"][0] == {"day": "2026-01-01", "count": 1}
    assert [d["day"] for d in s["date_summary"]] == sorted(d["day"] for d in s["date_summary"])
    rest = [it for it in items if it["rel"].rsplit("/", 1)[-1] > s["date_summary"][-1]["day"]]
    assert s["date_more"] == {"days": 5, "count": len(rest)} and s["to_copy"]["count"] == len(items)
    assert imp.summarize_plan(items[:2])["date_more"] is None


def test_summary_when_nothing_to_do():
    s = imp.summarize_plan([])
    assert s["date_summary"] == [] and s["date_more"] is None and s["to_copy"]["count"] == 0 and s["duplicates"]["count"] == 0


def test_prepare_reports_dates_across_days(tmp_path):
    card = tmp_path / "card"
    for i in range(3):
        make(card / f"a{i}.jpg", exif_jpeg("2026:11:14 09:30:05", pad=b"x" * i))
    make(card / "b.jpg", exif_jpeg("2026:11:13 09:30:05"))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    p = svc.prepare()
    assert p["date_summary"] == [{"day": "2026-11-13", "count": 1}, {"day": "2026-11-14", "count": 3}]
    assert "target" not in p and p["base"] == str(base)


# ---------------------------------------------------------------- 空间 / 取消 / 失效
def test_space_check_uses_only_files_that_will_be_copied(tmp_path):
    card = tmp_path / "card"
    dup = b"D" * 10_000_000
    make(card / "dup.png", dup)
    make(card / "new.png", b"N" * 1000)
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "z" / "have.png", dup)
    svc._free = lambda p: imp.SPACE_MARGIN + 5000        # 够放 1000 字节的新文件，不够放 10 MB 的重复文件
    scan(svc, card)
    p = svc.prepare()
    assert p["can_start"] and p["to_copy"]["size"] == 1000 and p["shortfall"] == 0
    svc._free = lambda p: imp.SPACE_MARGIN + 500
    p = svc.prepare()
    assert not p["can_start"] and "还差" in p["errors"]["space"] and p["shortfall"] == 500


def test_all_duplicates_do_not_trip_space_check(tmp_path):
    card = tmp_path / "card"
    make(card / "a.png", b"A" * 500)
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "z" / "a.png", b"A" * 500)
    svc._free = lambda p: 0
    scan(svc, card)
    p = svc.prepare()
    assert "all_duplicate" in p["errors"] and "space" not in p["errors"] and p["to_copy"]["count"] == 0


def test_cancel_while_analysing_gives_up_cleanly(tmp_path):
    card = tmp_path / "card"
    for i in range(5):
        make(card / f"{i}.png", b"S" * 50)               # 同大小：都要算哈希
    started = threading.Event()
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "x" / "lib.png", b"L" * 50)

    def slow_hash(path, should_cancel=lambda: False):
        started.set()
        while not should_cancel():
            time.sleep(0.01)
        raise imp.Cancelled()
    orig = imp.hash_file
    imp.hash_file = slow_hash
    try:
        assert svc.set_source(str(card))["ok"]
        assert started.wait(5)
        assert svc.stage == "scanning"
        assert svc.cancel()["ok"]
        assert wait(lambda: any(e.get("state") == "cancelled" for e in ev))
    finally:
        imp.hash_file = orig
    assert svc.stage == "idle" and svc.scan is None
    assert files_under(base) == ["x/lib.png"] and lr.calls == []


def test_progress_events_during_analysis(tmp_path):
    card = tmp_path / "card"
    for i in range(4):
        make(card / f"{i}.jpg", exif_jpeg(pad=bytes([i]) * i))
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    phases = [e for e in ev if e.get("type") == "import_scan" and e.get("phase") == "checking"]
    assert phases and phases[-1]["done"] == phases[-1]["total"] == 4
    done = [e for e in ev if e.get("type") == "import_scan" and e.get("state") == "done"][0]
    assert done["info"]["to_copy"] == 4 and done["info"]["duplicates"] == 0


def test_plan_cancel_returns_cancelled_flag(tmp_path):
    f = make(tmp_path / "card" / "a.png", 10)
    r = imp.plan_import([(str(f), 10)], tmp_path / "lib", should_cancel=lambda: True)
    assert r["cancelled"] is True and r["items"] == []


def test_changing_the_library_after_scan_requires_rescan(tmp_path):
    card = tmp_path / "card"
    make(card / "a.jpg", exif_jpeg())
    svc, lr, ev, base = mk_service(tmp_path)
    scan(svc, card)
    other = tmp_path / "other"
    other.mkdir()
    svc.settings.data["base_folder"] = str(other)
    p = svc.prepare()
    assert not p["can_start"] and "重新选择" in p["errors"]["base"]
    assert not svc.start()["ok"]


def test_missing_library_still_plans_dates_and_needs_consent(tmp_path):
    card = tmp_path / "card"
    make(card / "a.jpg", exif_jpeg())
    svc, lr, ev, base = mk_service(tmp_path)
    new = tmp_path / "brand_new_lib"
    svc.settings.data["base_folder"] = str(new)
    scan(svc, card)
    p = svc.prepare()
    assert p["can_start"] and not p["base_exists"] and p["date_summary"] == [{"day": "2026-11-14", "count": 1}]
    assert svc.start()["needs_create"]
    assert svc.start(create_base=True)["ok"] and wait(lambda: svc.stage == "done")
    assert files_under(new) == ["2026/2026-11-14/a.jpg"]


def test_source_inside_library_is_still_refused(tmp_path):
    base = tmp_path / "lib"
    make(base / "card" / "a.jpg", exif_jpeg())
    svc = isv.ImportService(Settings(base), FakeLr(), lambda e: None, data_dir=tmp_path / "LrMcp", sleep=lambda s: None)
    scan(svc, base / "card")
    p = svc.prepare()
    assert not p["can_start"] and "互相包含" in p["errors"]["base"]


def test_failures_and_duplicates_are_counted_separately(tmp_path):
    card = tmp_path / "card"
    c = exif_jpeg()
    make(card / "dupA.jpg", c)
    good = make(card / "good.jpg", exif_jpeg("2026:11:20 01:02:03"))
    gone = make(card / "gone.jpg", exif_jpeg("2026:11:21 01:02:03"))
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "q" / "dup_in_lib.jpg", c)
    scan(svc, card)
    gone.unlink()                                          # 扫描之后原文件消失：复制阶段失败
    res = run_import(svc)
    cnt = res["counts"]
    assert (cnt["duplicate"], cnt["copied"], cnt["failed"], cnt["lr_ok"]) == (1, 1, 1, 1)
    assert res["n"] == 2 and res["duplicates"]["count"] == 1 and len(res["problems"]) == 1
    assert good.exists()


def test_retry_lr_after_import_keeps_duplicate_counts(tmp_path):
    card = tmp_path / "card"
    c = exif_jpeg()
    make(card / "dup.jpg", c)
    make(card / "n.jpg", exif_jpeg("2026:11:20 01:02:03"))
    svc, lr, ev, base = mk_service(tmp_path)
    make(base / "q" / "d.jpg", c)
    lr.connected = False
    scan(svc, card)
    res = run_import(svc)
    assert res["counts"]["lr_pending"] == 1 and res["counts"]["duplicate"] == 1
    lr.connected = True
    assert svc.retry_lr()["ok"] and wait(lambda: svc.stage == "done")
    res = svc.state()["result"]
    assert res["counts"]["lr_ok"] == 1 and res["counts"]["duplicate"] == 1 and res["counts"]["copied"] == 1


def test_library_tree_shows_date_folders(tmp_path):
    make(tmp_path / "2026" / "2026-11-14" / "a.jpg")
    make(tmp_path / "2026" / "2026-11-15" / "b.jpg")
    make(tmp_path / "root.jpg")
    t = imp.library_tree(tmp_path)
    assert t["total"] == 3
    assert [g["name"] for g in t["groups"]] == ["（未分类）", "2026/2026-11-14", "2026/2026-11-15"]


def test_capture_date_module_is_what_the_planner_uses(tmp_path):
    f = make(tmp_path / "a.jpg", exif_jpeg("2001:02:03 04:05:06"))
    plan = imp.plan_import([(str(f), f.stat().st_size)], tmp_path / "lib")
    assert plan["items"][0]["rel"] == capture_date.date_folder(f, 0) == "2001/2001-02-03"
