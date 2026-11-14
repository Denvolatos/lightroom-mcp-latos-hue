# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.2.0 图库字段：排序所需字段、磁盘照片拍摄时间补全与缓存、排序设置随 state 返回、旧 gallery_folder 被忽略。"""
import os
from datetime import datetime

import pytest

import capture_date
import photo_library as pl
from preview import PreviewServer
from test_capture_date import jpeg_with, tiff_with
from test_photo_library import FakeLr, Settings, cat, env, touch   # noqa: F401 - env 是 fixture


def make_lib(base, lr=None, **kw):
    server = PreviewServer(pl.ThumbStore())
    server.port = 4321
    return pl.PhotoLibrary(Settings(base), lr or FakeLr(), lambda e: None, server, run_async=lambda fn: fn(), **kw)


def test_public_has_sort_fields_for_catalog_and_disk_only_photos(env):
    a = touch(env.base / "A.jpg", 123)
    ts = datetime(2026, 3, 4, 5, 6, 7).timestamp()
    os.utime(a, (ts, ts))
    touch(env.base / "2026" / "2026-11-14" / "B.arw", 77)
    env.lr.catalog = [cat(1, a, label="Red", edited=True, added_at="2026-11-01T08:00:00", captured="2026-03-04T05:06:07", rating=4)]
    env.lib.refresh_sync()
    pa, pb = sorted(env.lib.state()["photos"], key=lambda p: p["name"])
    assert pa["size"] == 123 and pa["mtime"] == pytest.approx(ts, abs=0.01) and pa["label"] == "red" and pa["edited"] is True
    assert pa["added_at"] == "2026-11-01T08:00:00" and pa["captured"] == "2026-03-04T05:06:07" and pa["rating"] == 4 and pa["format"] == "JPG"
    assert pb["size"] == 77 and pb["mtime"] > 0 and (pb["label"], pb["edited"], pb["added_at"]) == (None, None, None)
    assert pb["group"] == "2026/2026-11-14" and pb["added"] is False


@pytest.mark.parametrize("raw,expect", [("none", None), ("", None), (None, None), (5, None), ("  Blue ", "blue")])
def test_label_normalised(env, raw, expect):
    p = touch(env.base / "A.jpg")
    env.lr.catalog = [cat(1, p, label=raw)]
    env.lib.refresh_sync()
    assert env.lib.state()["photos"][0]["label"] == expect


@pytest.mark.parametrize("raw,expect", [(True, True), (False, False), (None, None), ("yes", None), (1, None)])
def test_edited_is_bool_or_none(env, raw, expect):
    p = touch(env.base / "A.jpg")
    env.lr.catalog = [cat(1, p, edited=raw)]
    env.lib.refresh_sync()
    assert env.lib.state()["photos"][0]["edited"] is expect


def test_old_plugin_without_new_fields_gives_none(env):
    p = touch(env.base / "A.jpg", 5)
    env.lr.catalog = [cat(1, p)]                 # cat() 不带 label/edited/added_at：旧插件
    env.lib.refresh_sync()
    ph = env.lib.state()["photos"][0]
    assert (ph["label"], ph["edited"], ph["added_at"]) == (None, None, None) and ph["size"] == 5


def test_missing_on_disk_catalog_photo_has_no_size(env):
    env.lr.catalog = [cat(1, env.base / "gone.jpg")]
    env.lib.refresh_sync()
    ph = env.lib.state()["photos"][0]
    assert ph["missing"] is True and ph["size"] is None and ph["mtime"] is None


def test_disk_only_photos_get_capture_date_from_file_header_and_it_is_cached(tmp_path):
    base = tmp_path / "lib"
    base.mkdir()
    (base / "a.jpg").write_bytes(jpeg_with(tiff_with("2026:11:14 09:30:05")))
    (base / "bad.jpg").write_bytes(b"not a jpeg at all")
    calls = []

    def counting(path):
        calls.append(os.path.basename(str(path)))
        return capture_date.capture_datetime(path)
    lib = make_lib(base, date_fn=counting)
    lib.refresh_sync()
    assert {p["name"]: p["captured"] for p in lib.state()["photos"]} == {"a.jpg": "2026-11-14T09:30:05", "bad.jpg": None}
    lib.refresh_sync()
    lib.refresh_sync()
    assert sorted(calls) == ["a.jpg", "bad.jpg"]                       # 没变的文件不重读
    (base / "a.jpg").write_bytes(jpeg_with(tiff_with("2027:01:02 03:04:05")))
    lib.refresh_sync()
    assert calls.count("a.jpg") == 2 and {p["name"]: p["captured"] for p in lib.state()["photos"]}["a.jpg"] == "2027-01-02T03:04:05"
    (base / "bad.jpg").unlink()
    lib.refresh_sync()
    assert "bad.jpg" not in lib._date_cache


def test_date_reader_exceptions_do_not_break_refresh(tmp_path):
    base = tmp_path / "lib"
    base.mkdir()
    touch(base / "a.jpg")

    def boom(path):
        raise RuntimeError("x")
    lib = make_lib(base, date_fn=boom)
    lib.refresh_sync()
    assert lib.state()["state"] == "ready" and lib.state()["photos"][0]["captured"] is None


def test_catalog_photos_do_not_read_file_headers(tmp_path):
    base = tmp_path / "lib"
    base.mkdir()
    p = touch(base / "a.jpg")

    def forbidden(path):
        raise AssertionError("不该读")
    lib = make_lib(base, FakeLr([cat(1, p, captured="2020-01-01T00:00:00")]), date_fn=forbidden)
    lib.refresh_sync()
    assert lib.state()["photos"][0]["captured"] == "2020-01-01T00:00:00"


def test_state_carries_sort_from_settings_with_fallbacks(env):
    s = env.lib.state()
    assert (s["sort"], s["order"]) == ("captured", "desc")             # 设置里没有这两项：默认
    env.lib.settings.data.update(gallery_sort="size", gallery_order="asc")
    s = env.lib.state()
    assert (s["sort"], s["order"]) == ("size", "asc")
    env.lib.settings.data.update(gallery_sort="bogus", gallery_order=7)
    s = env.lib.state()
    assert (s["sort"], s["order"]) == ("captured", "desc")


def test_gallery_ignores_stale_gallery_folder_setting(env, tmp_path):
    other = tmp_path / "other"
    touch(other / "X.jpg")
    touch(env.base / "A.jpg")
    env.lib.settings.data["gallery_folder"] = str(other)
    env.lr.catalog = []
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["base"] == str(env.base) and [p["name"] for p in s["photos"]] == ["A.jpg"]


def test_missing_base_folder_has_no_change_folder_wording(env, tmp_path):
    env.lib.settings.data["base_folder"] = str(tmp_path / "not_there")
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["base_exists"] is False and "换目录" not in s["message"]
