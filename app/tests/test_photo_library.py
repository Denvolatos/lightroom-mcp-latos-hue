# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件内图库（photo_library）：两路数据合并、缩略图分批与缓存、选中同步、加入 Lightroom、Api 参数校验。
假 Lightroom、假图片服务、临时目录；不连真实 Lightroom。"""
import inspect
import os
import threading
import time
from pathlib import Path

import pytest

import importer as imp
import photo_library as pl
import settings as st
from preview import PreviewServer


class Settings:
    def __init__(self, base):
        self.data = {"base_folder": str(base)}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


JPEG = b"\xff\xd8\xff" + b"x" * 100


class FakeLr:
    """catalog = [{"id","name","path",...}]；按插件的行为分页、在“视图”里选中。"""

    def __init__(self, catalog=None, connected=True):
        self.connected = connected
        self.catalog = list(catalog or [])
        self.in_catalog = True
        self.list_calls = []
        self.thumb_calls = []
        self.select_calls = []
        self.imported = []
        self.readonly = None
        self.thumb_fail = {}
        self.select_result = None          # 覆盖 select 返回
        self.select_error = None
        self.lr_selection = {"count": 0, "active_id": None, "photos": []}
        self.meta = {}
        self.import_status = {}            # 路径 -> status
        self.thumb_bytes = JPEG

    def library_list(self, path, offset=0, limit=500):
        self.list_calls.append((path, offset, limit))
        if not self.in_catalog:
            return {"in_catalog": False, "total": 0, "offset": offset, "photos": []}
        page = self.catalog[offset:offset + limit]
        return {"in_catalog": True, "total": len(self.catalog), "offset": offset, "photos": page}

    def library_thumbnails(self, ids, size=256):
        self.thumb_calls.append(list(ids))
        out = []
        for i in ids:
            if i in self.thumb_fail:
                out.append({"id": i, "ok": False, "error": self.thumb_fail[i]})
            else:
                out.append({"id": i, "ok": True, "jpeg": self.thumb_bytes, "width": 320, "height": 213, "bytes": len(self.thumb_bytes)})
        return {"size": size, "thumbnails": out}

    def library_select(self, ids, active, show_folder):
        self.select_calls.append((list(ids), active, show_folder))
        if self.select_error:
            raise self.select_error
        if self.select_result is not None:
            return self.select_result
        return {"status": "selected", "selected": list(ids), "missing": [], "not_selected": [], "all_selected": True,
                "folder_shown": True, "reason": None}

    def selected_all(self, limit=20):
        return self.lr_selection

    def metadata_of(self, pid):
        if pid not in self.meta:
            raise RuntimeError("no")
        return {"metadata": self.meta[pid]}

    def readonly_error(self):
        return self.readonly

    def import_photo(self, path):
        self.imported.append(path)
        return {"status": self.import_status.get(path, "imported")}


def cat(i, path, **kw):
    d = {"id": str(100 + i), "name": os.path.basename(path), "path": str(path), "subfolder": "", "format": "JPG", "rating": None,
         "flag": "none", "captured": None, "width": 100, "height": 80, "is_virtual_copy": False}
    d.update(kw)
    return d


def touch(p: Path, n=10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)
    return p


class Env:
    pass


@pytest.fixture
def env(tmp_path):
    e = Env()
    e.base = tmp_path / "lib"
    e.base.mkdir()
    e.lr = FakeLr()
    e.events = []
    e.clock = Clock()
    e.server = PreviewServer(pl.ThumbStore())
    e.server.port = 4321
    e.selected_calls = []
    e.lib = pl.PhotoLibrary(Settings(e.base), e.lr, e.events.append, e.server, on_selected=lambda: e.selected_calls.append(1),
                            run_async=lambda fn: fn(), dirty_delay=1.0, clock=e.clock, sleep=lambda s: None)
    return e


def seed(e, n_root=3, n_sub=2, sub="test_batch"):
    """磁盘与目录各有 n_root + n_sub 张，路径一致。"""
    cats = []
    for i in range(n_root):
        cats.append(cat(i, touch(e.base / f"R{i}.jpg")))
    for i in range(n_sub):
        cats.append(cat(10 + i, touch(e.base / sub / f"S{i}.arw"), format="RAW"))
    e.lr.catalog = cats
    return cats


# ---------------------------------------------------------------- 路径规范化与分组
def test_norm_key_case_slashes_and_trailing():
    assert pl.norm_key("D:/Ceshi//App\\Test/A.JPG") == "d:\\ceshi\\app\\test\\a.jpg"
    assert pl.norm_key("D:\\x\\") == "d:\\x"
    assert pl.norm_key("D:\\") == "d:\\"
    assert pl.norm_key(None) == ""


def test_group_of():
    assert pl.group_of("D:\\lib\\a.jpg", "D:\\lib") == pl.GROUP_ROOT
    assert pl.group_of("D:\\LIB\\sub\\a.jpg", "d:\\lib\\") == "sub"
    assert pl.group_of("D:/lib/a/b/c.jpg", "D:\\lib") == "a/b"
    assert pl.group_of("E:\\other\\a.jpg", "D:\\lib", "其他") == "其他"
    assert pl.group_of("D:\\library2\\a.jpg", "D:\\lib") == pl.GROUP_ROOT        # 前缀相同但不是子文件夹


def test_sort_groups_root_first_and_orders():
    ps = [{"group": "b", "name": "z.jpg", "captured": "2026-01-02"}, {"group": pl.GROUP_ROOT, "name": "B.jpg", "captured": None},
          {"group": "a", "name": "m.jpg", "captured": None}, {"group": pl.GROUP_ROOT, "name": "a.jpg", "captured": "2026-01-01"},
          {"group": "b", "name": "c.jpg", "captured": "2026-01-03"}]
    g = pl.sort_groups(ps, "name")
    assert [x["name"] for x in g] == [pl.GROUP_ROOT, "a", "b"] and [x["count"] for x in g] == [2, 1, 2]
    assert [p["name"] for p in g[0]["photos"]] == ["a.jpg", "B.jpg"] and [p["name"] for p in g[2]["photos"]] == ["c.jpg", "z.jpg"]
    t = pl.sort_groups(ps, "time")
    assert [p["name"] for p in t[0]["photos"]] == ["a.jpg", "B.jpg"]              # 有拍摄时间的在前，没有的在后
    assert [p["name"] for p in t[2]["photos"]] == ["z.jpg", "c.jpg"]


# ---------------------------------------------------------------- 两路数据合并
def test_refresh_merges_and_groups(env):
    seed(env)
    env.lib.refresh()
    s = env.lib.state()
    assert s["state"] == "ready" and s["total"] == 5 and s["in_catalog"] and not s["truncated"]
    assert s["not_added"] == 0 and s["missing"] == 0
    groups = {}
    for p in s["photos"]:
        groups.setdefault(p["group"], []).append(p["name"])
    assert groups == {pl.GROUP_ROOT: ["R0.jpg", "R1.jpg", "R2.jpg"], "test_batch": ["S0.arw", "S1.arw"]}
    assert {"type": "library_changed"} in env.events
    assert env.lr.list_calls[0][0] == str(env.base)                           # 只用设置里的软件文件夹


def test_not_added_and_missing_flags(env):
    cats = seed(env)
    touch(env.base / "new_test" / "NEW.JPG")                                  # 磁盘上有，目录里没有
    os.remove(cats[1]["path"])                                                # 目录里有，磁盘上没有
    env.lib.refresh_sync()
    s = env.lib.state()
    by = {p["name"]: p for p in s["photos"]}
    assert by["NEW.JPG"]["added"] is False and by["NEW.JPG"]["missing"] is False and by["NEW.JPG"]["id"].startswith("n-")
    assert by["R1.jpg"]["missing"] is True and by["R1.jpg"]["added"] is True
    assert by["R0.jpg"]["missing"] is False
    assert s["not_added"] == 1 and s["missing"] == 1 and by["NEW.JPG"]["group"] == "new_test"


def test_path_match_ignores_case_and_slash_style(env):
    p = touch(env.base / "Sub" / "Photo.JPG")
    env.lr.catalog = [cat(1, str(p).upper().replace("\\", "/"))]              # 目录里的写法大小写/斜杠不同
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["total"] == 1 and s["not_added"] == 0 and s["missing"] == 0
    assert s["photos"][0]["group"] == "Sub" or s["photos"][0]["group"] == "SUB"


def test_virtual_copies_are_separate_records(env):
    p = touch(env.base / "A.jpg")
    env.lr.catalog = [cat(1, p), cat(2, p, is_virtual_copy=True)]
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["total"] == 2 and sorted(x["vc"] for x in s["photos"]) == [False, True] and s["not_added"] == 0


def test_rating_flag_fields(env):
    p = touch(env.base / "A.jpg")
    q = touch(env.base / "B.jpg")
    env.lr.catalog = [cat(1, p, rating=4, flag="pick"), cat(2, q, rating=None, flag="weird")]
    env.lib.refresh_sync()
    by = {x["name"]: x for x in env.lib.state()["photos"]}
    assert by["A.jpg"]["rating"] == 4 and by["A.jpg"]["flag"] == "pick"
    assert by["B.jpg"]["rating"] is None and by["B.jpg"]["flag"] == "none"


def test_disk_scan_rules_reused(env):
    touch(env.base / "a.jpg")
    touch(env.base / "notes.txt")                                             # 扩展名不在白名单
    touch(env.base / ".hidden" / "h.jpg")                                     # 隐藏目录
    touch(env.base / "$RECYCLE.BIN" / "r.jpg")
    deep = env.base
    for i in range(8):
        deep = deep / f"d{i}"
    touch(deep / "deep.jpg")                                                  # 超过深度 6
    env.lr.in_catalog = False
    env.lib.refresh_sync()
    names = [p["name"] for p in env.lib.state()["photos"]]
    assert names == ["a.jpg"]


def test_paging_fetches_everything(env):
    env.lr.catalog = [cat(i, env.base / f"p{i:05}.jpg") for i in range(1200)]
    env.lib.refresh_sync()
    assert [(c[1], c[2]) for c in env.lr.list_calls] == [(0, 500), (500, 500), (1000, 500)]
    s = env.lib.state()
    assert s["total"] == 1200 and not s["truncated"] and s["missing"] == 1200       # 磁盘上没有这些文件


def test_cap_2000_and_truncated_message(env):
    env.lr.catalog = [cat(i, env.base / f"p{i:05}.jpg") for i in range(2300)]
    touch(env.base / "only_on_disk.jpg")
    env.lib.refresh_sync()
    assert [c[1] for c in env.lr.list_calls] == [0, 500, 1000, 1500]
    assert env.lr.list_calls[-1][2] == 500
    s = env.lib.state()
    assert s["total"] == 2000 and s["truncated"] is True and s["truncated_message"] == "仅显示前 2000 张。"
    assert all(p["added"] for p in s["photos"])                               # 目录没取全：不判断“尚未加入”


def test_empty_states(env):
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["state"] == "ready" and s["total"] == 0 and s["base_exists"] is True and s["base"] == str(env.base)
    env.lib.settings.data["base_folder"] = str(env.base / "missing")
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["state"] == "ready" and s["total"] == 0 and s["base_exists"] is False
    assert len(env.lr.list_calls) == 1                                        # 文件夹不存在：不去问 Lightroom


def test_lightroom_not_connected(env):
    seed(env)
    env.lr.connected = False
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["state"] == "error" and s["message"] == "Lightroom 未连接，无法显示照片信息" and s["photos"] == [] and s["lr_connected"] is False


def test_folder_not_in_catalog_marks_everything_not_added(env):
    touch(env.base / "a.jpg")
    touch(env.base / "b.jpg")
    env.lr.in_catalog = False
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["total"] == 2 and s["not_added"] == 2 and s["in_catalog"] is False


def test_catalog_errors_translated(env):
    class PluginNotConnected(Exception):
        pass

    def boom(*a, **k):
        raise PluginNotConnected("x")
    env.lr.library_list = boom
    env.lib.refresh_sync()
    assert env.lib.state()["message"] == "Lightroom 未连接，无法显示照片信息"
    env.lr.library_list = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("插件拒绝了请求"))
    env.lib.refresh_sync()
    assert env.lib.state()["message"] == "插件拒绝了请求"


def test_refresh_failure_keeps_previous_list_and_selection(env):
    """1.1.1：刷新失败一次不再清空整个列表和选区；保留上一次结果，只提示“暂时无法更新”。"""
    seed(env)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.select([ids[0]])
    for breakit, fixit in (
            (lambda: setattr(env.lr, "connected", False), lambda: setattr(env.lr, "connected", True)),
            (lambda: setattr(env.lr, "library_list", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("插件忙"))),
             lambda: env.lr.__dict__.pop("library_list"))):
        breakit()
        env.lib.refresh_sync()
        s = env.lib.state()
        assert s["state"] == "ready" and s["stale"] is True and len(s["photos"]) == 5
        assert s["message"].startswith(pl.MSG_STALE_PREFIX) and s["selection"]["ids"] == [ids[0]]
        fixit()
        env.lib.refresh_sync()
        s = env.lib.state()
        assert s["state"] == "ready" and s["stale"] is False and s["message"] == "" and len(s["photos"]) == 5


def test_refresh_failure_without_previous_result_or_after_folder_change_is_an_error(env, tmp_path):
    env.lr.connected = False
    env.lib.refresh_sync()
    assert env.lib.state()["state"] == "error" and env.lib.state()["stale"] is False
    env.lr.connected = True
    seed(env)
    env.lib.refresh_sync()
    other = tmp_path / "other"
    other.mkdir()
    env.lib.settings.data["base_folder"] = str(other)                         # 换了目录：旧目录的列表不能冒充新目录
    env.lr.connected = False
    env.lib.refresh_sync()
    s = env.lib.state()
    assert s["state"] == "error" and s["photos"] == []


def test_refresh_coalesces_while_running(tmp_path):
    started = threading.Event()
    release = threading.Event()
    lr = FakeLr()
    base = tmp_path / "b"
    base.mkdir()
    orig = lr.library_list

    def slow(*a, **k):
        started.set()
        release.wait(5)
        return orig(*a, **k)
    lr.library_list = slow
    lib = pl.PhotoLibrary(Settings(base), lr, lambda e: None, PreviewServer(pl.ThumbStore()))
    assert lib.refresh()["started"] is True
    assert started.wait(2)
    assert lib.state()["state"] == "loading"
    assert lib.refresh()["started"] is False                                  # 已在刷新：只排一次补刷
    release.set()
    end = time.time() + 5
    while time.time() < end and (lib._refreshing or len(lr.list_calls) < 2):
        time.sleep(0.01)
    assert len(lr.list_calls) == 2 and lib.state()["state"] == "ready"


def test_state_keeps_old_photos_while_reloading(env):
    seed(env)
    env.lib.refresh_sync()
    env.lib.state_name = "loading"
    assert len(env.lib.state()["photos"]) == 5                                # 刷新期间不清空列表


# ---------------------------------------------------------------- 缩略图缓存
def test_thumbstore_lru_by_count_and_bytes_and_invalidate():
    s = pl.ThumbStore(max_items=3, max_bytes=1000)
    for i in range(4):
        s.put(f"p{i}", 256, "t", b"x" * 100)
    assert len(s) == 3 and s.peek("p0") is None and s.peek("p3") is not None
    s.get("p1", 256, "t")                                                     # 用一下 p1：它不再是最久未用
    s.put("p4", 256, "t", b"x" * 100)
    assert s.peek("p2") is None and s.peek("p1") is not None
    assert s.total_bytes == 300
    b = pl.ThumbStore(max_items=100, max_bytes=250)
    for i in range(5):
        b.put(f"q{i}", 256, "t", b"y" * 100)
    assert b.total_bytes <= 250 and len(b) == 2 and b.peek("q4") is not None and b.peek("q0") is None
    old = b.peek("q4")
    b.put("q4", 256, "t", b"z" * 50)                                          # 同键覆盖：旧条目消失、字节数正确
    assert b.bytes_of(old["id"]) is None and b.total_bytes == 150
    assert b.invalidate("q4") == 1 and b.peek("q4") is None and b.total_bytes == 100
    assert b.invalidate("nope") == 0


def test_thumbstore_defaults_match_spec():
    s = pl.ThumbStore()
    assert s._max_cache == 500 and s.max_bytes == 64 * 1024 * 1024


def test_thumbnails_batches_of_at_most_8_and_cache_hits(env):
    env.lr.catalog = [cat(i, touch(env.base / f"p{i:02}.jpg")) for i in range(20)]
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    r = env.lib.request_thumbs(ids)
    assert r["ok"] and r["thumbs"] == {} and r["pending"] == ids
    n = 0
    while env.lib.process_thumbs_once():
        n += 1
    assert n == 3 and [len(c) for c in env.lr.thumb_calls] == [8, 8, 4] and all(len(c) <= pl.THUMB_BATCH for c in env.lr.thumb_calls)
    items = [i for e in env.events if e["type"] == "library_thumbs" for i in e["items"]]
    assert len(items) == 20 and all(i["url"].startswith("http://127.0.0.1:4321/p/") for i in items)
    r2 = env.lib.request_thumbs(ids)                                          # 第二次全部命中缓存，不再向 Lightroom 取
    assert r2["pending"] == [] and len(r2["thumbs"]) == 20 and len(env.lr.thumb_calls) == 3
    assert env.lib.process_thumbs_once() is False
    assert env.lib.stats["hits"] == 20 and env.lib.stats["requested"] == 40 and env.lib.cache_hit_rate() == 0.5
    assert env.lib.stats["fetched"] == 20 and env.lib.stats["batch_max"] == 8
    assert len(env.lib.state()["thumbs"]) == 20                               # 页面重新加载时能拿到已缓存的 URL


def test_thumbnail_url_serves_cached_bytes(env):
    seed(env, 1, 0)
    env.lib.refresh_sync()
    pid = env.lib.state()["photos"][0]["id"]
    env.lib.request_thumbs([pid])
    env.lib.process_thumbs_once()
    url = [i for e in env.events if e["type"] == "library_thumbs" for i in e["items"]][0]["url"]
    entry_id = url.rsplit("/", 1)[1][:-4]
    assert env.server.store.bytes_of(entry_id) == JPEG


def test_new_request_replaces_unstarted_queue(env):
    env.lr.catalog = [cat(i, touch(env.base / f"p{i:02}.jpg")) for i in range(30)]
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.request_thumbs(ids[:20])
    env.lib.request_thumbs(ids[20:25])                                        # 页面滚动了：前面排队的不再需要
    env.lib.process_thumbs_once()
    assert env.lr.thumb_calls == [ids[20:25]]


def test_failed_thumbnails_and_retry(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lr.thumb_fail = {ids[1]: "too_large", ids[2]: "not_found"}
    env.lib.request_thumbs(ids)
    env.lib.process_thumbs_once()
    env.lib.process_thumbs_once()                                              # too_large 自动再试了一次，仍失败
    ev = [i for e in env.events if e["type"] == "library_thumbs" for i in e["items"]]
    err = {i["id"]: i["error"] for i in ev if "error" in i}
    assert err == {ids[1]: "缩略图过大（超过 150 KB），无法显示", ids[2]: "照片在 Lightroom 目录中不存在"}
    r = env.lib.request_thumbs(ids)                                           # 不重试：失败的直接给错误，不再排队
    assert r["pending"] == [] and set(r["thumbs"][ids[1]]) == {"error"} and len(env.lr.thumb_calls) == 2
    env.lr.thumb_fail = {}
    r = env.lib.request_thumbs(ids, retry=True)
    assert r["pending"] == [ids[1], ids[2]]
    env.lib.process_thumbs_once()
    assert env.lr.thumb_calls[-1] == [ids[1], ids[2]] and env.lib.state()["failed"] == {}


def test_timeout_is_retried_once_automatically(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lr.thumb_fail = {ids[0]: "timeout"}
    env.lib.request_thumbs(ids)
    env.lib.process_thumbs_once()
    assert env.lib.state()["failed"] == {}                                     # 第一次超时：不报失败，排队再试
    assert [i["id"] for e in env.events if e["type"] == "library_thumbs" for i in e["items"]] == [ids[1]]
    env.lib.process_thumbs_once()                                              # 再试仍超时：才算失败
    assert env.lr.thumb_calls[-1] == [ids[0]] and env.lib.state()["failed"] == {ids[0]: "读取缩略图超时"}
    assert env.lib.process_thumbs_once() is False                              # 只试一次，不会一直重试
    env.lr.thumb_fail = {}
    env.lib.request_thumbs(ids, retry=True)                                    # 用户点“重试”：重新开始
    env.lib.process_thumbs_once()
    assert ids[0] in env.lib.state()["thumbs"]


def test_unknown_error_code_is_shown_in_message(env):
    seed(env, 1, 0)
    env.lib.refresh_sync()
    pid = env.lib.state()["photos"][0]["id"]
    env.lr.thumb_fail = {pid: "Lightroom 说：渲染失败"}
    env.lib.request_thumbs([pid])
    env.lib.process_thumbs_once()
    assert env.lib.state()["failed"][pid] == "无法读取缩略图（Lightroom 说：渲染失败）"


def test_whole_batch_failure_marks_every_photo(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]

    class BridgeTimeout(Exception):
        pass
    env.lr.library_thumbnails = lambda *a, **k: (_ for _ in ()).throw(BridgeTimeout("x"))
    env.lib.request_thumbs(ids)
    env.lib.process_thumbs_once()
    assert set(env.lib.state()["failed"]) == set(ids)
    assert all("时限" in m for m in env.lib.state()["failed"].values())


def test_thumbnail_request_validation(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    pid = env.lib.state()["photos"][0]["id"]
    assert env.lib.request_thumbs("101")["ok"] is False                        # 不是列表
    assert env.lib.request_thumbs([1])["ok"] is False
    assert env.lib.request_thumbs(["../x"])["ok"] is False
    assert env.lib.request_thumbs(["999"])["ok"] is False                      # 不在当前图库
    assert env.lib.request_thumbs([pid] * 201)["ok"] is False                  # 超过一次请求上限
    assert env.lib.request_thumbs([pid, pid])["pending"] == [pid]              # 重复项合并
    assert env.lr.thumb_calls == []


def test_not_added_photo_has_no_thumbnail_and_is_not_queued(env):
    touch(env.base / "new.jpg")
    env.lr.in_catalog = False
    env.lib.refresh_sync()
    pid = env.lib.state()["photos"][0]["id"]
    r = env.lib.request_thumbs([pid])
    assert r["pending"] == [] and "尚未加入" in r["thumbs"][pid]["error"]
    assert env.lib.process_thumbs_once() is False


def test_invalidate_drops_cache_and_refetches_after_delay(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.request_thumbs(ids)
    env.lib.process_thumbs_once()
    first = {i["id"]: i["url"] for e in env.events if e["type"] == "library_thumbs" for i in e["items"]}
    assert env.lib.invalidate_thumbs([ids[0], "not-in-library"]) == 1
    assert env.lib.state()["thumbs"].keys() == {ids[1]}                        # 缓存已失效
    assert env.lib.process_thumbs_once() is False                              # 还没到等待时间（让 Lightroom 更新预览）
    env.clock.t += 1.5
    assert env.lib.process_thumbs_once() is True and env.lr.thumb_calls[-1] == [ids[0]]
    newest = [i for e in env.events if e["type"] == "library_thumbs" for i in e["items"] if i["id"] == ids[0]][-1]["url"]
    assert newest != first[ids[0]]                                             # 新的 URL，页面会重新加载
    assert env.lib.stats["fetched"] == 3


def test_invalidate_during_flight_discards_result(env):
    seed(env, 1, 0)
    env.lib.refresh_sync()
    pid = env.lib.state()["photos"][0]["id"]
    env.lib.request_thumbs([pid])
    orig = env.lr.library_thumbnails

    def during(ids, size=256):
        env.lib.invalidate_thumbs([pid])                                       # 取图过程中照片又被调整了
        return orig(ids, size)
    env.lr.library_thumbnails = during
    env.lib.process_thumbs_once()
    assert env.lib.state()["thumbs"] == {}                                     # 作废的结果不入缓存
    env.lr.library_thumbnails = orig
    env.clock.t += 2
    assert env.lib.process_thumbs_once() is True and pid in env.lib.state()["thumbs"]


def test_thumbs_not_in_library_after_refresh_dropped(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.request_thumbs(ids)
    env.lr.catalog = env.lr.catalog[:1]
    env.lib.refresh_sync()
    env.lib.process_thumbs_once()
    assert env.lr.thumb_calls == [ids[:1]] or env.lr.thumb_calls == []


# ---------------------------------------------------------------- 星级与旗标刷新
def test_refresh_meta_updates_cells(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lr.meta = {ids[0]: {"rating": 5, "flag": "pick"}, ids[1]: {"rating": 0, "flag": "reject"}}
    env.lib.refresh_meta([ids[0], ids[1], ids[2], "zzz", None])                 # ids[2] 读不到：保持旧值；未知 id 忽略
    by = {p["id"]: p for p in env.lib.state()["photos"]}
    assert (by[ids[0]]["rating"], by[ids[0]]["flag"]) == (5, "pick") and (by[ids[1]]["rating"], by[ids[1]]["flag"]) == (0, "reject")
    assert by[ids[2]]["rating"] is None
    ev = [e for e in env.events if e["type"] == "library_meta"][-1]
    assert {i["id"] for i in ev["items"]} == {ids[0], ids[1]}


def test_refresh_meta_many_ids_falls_back_to_full_refresh(env):
    env.lr.catalog = [cat(i, touch(env.base / f"p{i:02}.jpg")) for i in range(25)]
    env.lib.refresh_sync()
    n = len(env.lr.list_calls)
    env.lib.refresh_meta([p["id"] for p in env.lib.state()["photos"]])
    assert len(env.lr.list_calls) > n


# ---------------------------------------------------------------- 选中
def test_select_validation_rejects_bad_input_without_calling_lightroom(env):
    seed(env, 3, 0)
    touch(env.base / "new.jpg")
    env.lib.refresh_sync()
    by = {p["name"]: p["id"] for p in env.lib.state()["photos"]}
    a, new = by["R0.jpg"], by["new.jpg"]
    for bad in ("101", None, [], [1], ["../../x"], ["999"], [a, "999"], [new], [a, new]):
        r = env.lib.select(bad)
        assert r["ok"] is False and r["status"] == "refused" and r["message"], bad
    assert env.lib.select([a], active="102")["status"] == "refused"           # active 必须在 ids 里
    assert env.lib.select([a], active=5)["status"] == "refused"
    assert env.lr.select_calls == []


def test_select_model_cases_and_limit_50(env):
    env.lr.catalog = [cat(i, touch(env.base / f"p{i:02}.jpg")) for i in range(60)]
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    r = env.lib.select([ids[0]])                                              # 单选
    assert r["ok"] and r["selected"] == [ids[0]] and r["active"] == ids[0]
    r = env.lib.select([ids[0], ids[2]], active=ids[2])                       # Ctrl 增加
    assert r["selected"] == [ids[0], ids[2]] and r["active"] == ids[2]
    r = env.lib.select(ids[3:8], active=ids[7])                               # Shift 区间
    assert r["selected"] == ids[3:8] and r["active"] == ids[7]
    r = env.lib.select(ids[:50])                                              # 全选：恰好 50 张
    assert r["ok"] and len(r["selected"]) == 50
    r = env.lib.select(ids[:51])
    assert r["ok"] is False and "最多选择 50" in r["message"] and len(env.lr.select_calls) == 4
    assert env.lib.select([ids[1], ids[1]])["selected"] == [ids[1]]           # 重复的合并
    assert env.lr.select_calls[0] == ([ids[0]], None, None)                    # 1.1.1：先直接选，不切换文件夹
    assert env.lr.select_calls[1][1] == ids[2]


def test_select_retries_once_with_the_photos_own_folder_only_when_not_selected(env):
    seed(env, 2, 2, sub="子文件夹")
    env.lib.refresh_sync()
    by = {p["name"]: p["id"] for p in env.lib.state()["photos"]}
    a, s0 = by["R0.jpg"], by["S0.arw"]
    calls = []

    def sel(ids, active, show_folder):
        calls.append(show_folder)
        if show_folder is None and s0 in ids:                                 # 第一次：子文件夹里的照片不在当前来源里，选不中
            return {"status": "partial", "selected": [i for i in ids if i == a], "not_selected": [i for i in ids if i != a],
                    "all_selected": False, "reason": "不在当前文件夹"}
        return {"status": "selected", "selected": list(ids), "not_selected": [], "all_selected": True}
    env.lr.library_select = sel
    r = env.lib.select([a, s0], active=s0)
    assert calls == [None, str(env.base / "子文件夹")]                          # 只重试一次，带的是照片自己的文件夹
    assert r["ok"] and r["selected"] == [a, s0] and r["active"] == s0
    calls.clear()
    assert env.lib.select([a])["ok"] and calls == [None]                       # 直接选中：不切换文件夹


def test_select_does_not_retry_when_uncertain_or_folder_gone(env):
    seed(env, 1, 1, sub="sub")
    env.lib.refresh_sync()
    by = {p["name"]: p["id"] for p in env.lib.state()["photos"]}
    env.lr.select_result = {"status": "uncertain", "selected": [], "not_selected": [], "all_selected": False}
    env.lib.select([by["S0.arw"]])
    assert [c[2] for c in env.lr.select_calls] == [None]
    import shutil
    shutil.rmtree(env.base / "sub")
    env.lr.select_calls.clear()
    env.lr.select_result = {"status": "partial", "selected": [], "not_selected": [by["S0.arw"]], "all_selected": False}
    env.lib.select([by["S0.arw"]])
    assert [c[2] for c in env.lr.select_calls] == [None]                       # 文件夹已不在：不重试


def test_select_calls_on_selected_and_emits(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    r = env.lib.select(ids, active=ids[1])
    assert r["ok"] and env.selected_calls == [1]                               # 立即刷新“当前照片”
    assert {"type": "library_selection", "ids": ids, "active": ids[1]} in env.events
    assert env.lib.state()["selection"] == {"ids": ids, "active": ids[1]}


def test_select_partial_uses_actual_selection_and_states_reason(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lr.select_result = {"status": "partial", "selected": ids[:2], "missing": [], "not_selected": [ids[2]], "all_selected": False,
                            "folder_shown": False, "reason": "有照片没有被选中：它们可能不在 Lightroom 当前显示的文件夹或集合里。"}
    r = env.lib.select(ids, active=ids[2])
    assert r["ok"] is False and r["status"] == "partial"
    assert r["selected"] == ids[:2] and r["not_selected"] == [ids[2]]          # 以 Lightroom 实际选区为准，不假装成功
    assert r["message"].startswith("Lightroom 未能选中其中 1 张照片。") and "不在 Lightroom 当前显示" in r["message"]
    assert env.lib.state()["selection"]["ids"] == ids[:2] and env.lib.state()["selection"]["active"] == ids[1]


def test_select_uncertain_reads_back_lightroom_selection(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lr.select_result = {"status": "uncertain", "selected": [], "missing": [], "not_selected": [], "all_selected": False,
                            "folder_shown": None, "reason": None}
    env.lr.lr_selection = {"count": 1, "active_id": ids[2], "photos": [{"id": ids[2], "name": "x"}]}
    r = env.lib.select([ids[0]])
    assert r["ok"] is False and r["status"] == "uncertain" and "不确定" in r["message"]
    assert r["selected"] == [ids[2]] and r["active"] == ids[2]


def test_select_errors_are_reported_and_state_follows_lightroom(env):
    seed(env, 2, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]

    class PluginNotConnected(Exception):
        pass
    env.lr.select_error = PluginNotConnected("x")
    env.lr.lr_selection = {"count": 1, "active_id": ids[1], "photos": [{"id": ids[1], "name": "x"}]}
    r = env.lib.select([ids[0]])
    assert r["ok"] is False and r["status"] == "failed" and r["message"] == "Lightroom 未连接，无法显示照片信息"
    assert r["selected"] == [ids[1]]
    assert env.selected_calls == [1]                                           # 有选区就刷新当前照片


def test_select_ignores_lightroom_events_while_selecting(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    seen = []
    orig = env.lr.library_select

    def during(i, a, f):
        env.lib.on_lr_selection({"count": 1, "active_id": ids[2], "photos": [{"id": ids[2]}]})     # 轮询在途中读到旧选区
        seen.append(list(env.lib.sel_ids))
        return orig(i, a, f)
    env.lr.library_select = during
    env.lib.select([ids[0]])
    assert seen == [[]] and env.lib.sel_ids == [ids[0]]


def test_lightroom_selection_events_update_highlight(env):
    seed(env, 4, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    n = len(env.events)
    env.lib.on_lr_selection({"count": 2, "active_id": ids[1], "photos": [{"id": ids[0]}, {"id": ids[1]}]})
    assert env.lib.state()["selection"] == {"ids": ids[:2], "active": ids[1]} and env.events[n]["type"] == "library_selection"
    n = len(env.events)
    env.lib.on_lr_selection({"count": 2, "active_id": ids[1], "photos": [{"id": ids[0]}, {"id": ids[1]}]})     # 没变化：不重复通知
    assert len(env.events) == n
    env.lib.on_lr_selection({"count": 1, "active_id": "other", "photos": [{"id": "other"}]})                    # 选了图库之外的照片
    assert env.lib.state()["selection"] == {"ids": [], "active": None}


def test_lightroom_event_truncated_to_20_keeps_big_selection(env):
    env.lr.catalog = [cat(i, touch(env.base / f"p{i:02}.jpg")) for i in range(40)]
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.select(ids[:30], active=ids[0])
    n = len(env.events)
    env.lib.on_lr_selection({"count": 30, "active_id": ids[0], "photos": [{"id": i} for i in ids[:20]]})        # 事件只带前 20 张
    assert len(env.events) == n and len(env.lib.state()["selection"]["ids"]) == 30
    env.lib.on_lr_selection({"count": 25, "active_id": ids[0], "photos": [{"id": i} for i in ids[:20]]})        # 数量变了：以 Lightroom 为准
    assert len(env.lib.state()["selection"]["ids"]) == 20


def test_clear_selection_suppresses_until_lightroom_changes(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    ev = {"count": 1, "active_id": ids[0], "photos": [{"id": ids[0]}]}
    env.lib.on_lr_selection(ev)
    r = env.lib.clear_selection()
    assert r["ok"] and "Lightroom 里的选区不变" in r["message"]
    assert env.lib.state()["selection"] == {"ids": [], "active": None}
    env.lib.on_lr_selection(dict(ev))                                          # Lightroom 选区没变：不再重新标出来
    assert env.lib.state()["selection"]["ids"] == []
    env.lib.on_lr_selection({"count": 1, "active_id": ids[1], "photos": [{"id": ids[1]}]})                       # 变了就跟随
    assert env.lib.state()["selection"]["ids"] == [ids[1]]


def test_refresh_drops_selection_of_photos_that_vanished(env):
    seed(env, 3, 0)
    env.lib.refresh_sync()
    ids = [p["id"] for p in env.lib.state()["photos"]]
    env.lib.select(ids, active=ids[2])
    env.lr.catalog = env.lr.catalog[:1]
    env.lib.refresh_sync()
    assert env.lib.state()["selection"] == {"ids": [ids[0]], "active": ids[0]}


# ---------------------------------------------------------------- 加入 Lightroom
def add_env(env):
    seed(env, 2, 0)
    touch(env.base / "new1.jpg")
    touch(env.base / "sub" / "new2.arw")
    env.lib.refresh_sync()
    assert env.lib.state()["not_added"] == 2


def test_add_missing_success_in_order_and_refreshes(env):
    add_env(env)
    r = env.lib.add_missing()
    assert r == {"ok": True, "n": 2}
    assert [os.path.basename(p) for p in env.lr.imported] == ["new1.jpg", "new2.arw"]      # 顺序固定、逐张
    st_ = env.lib.add_state()
    assert st_["state"] == "done" and st_["counts"]["added"] == 2 and st_["problems"] == []
    assert [e for e in env.events if e["type"] == "library_add"][-1]["state"] == "done"
    assert any(e["type"] == "library_add" and e["state"] == "running" for e in env.events)
    assert env.lib.close_add() == {"ok": True} and env.lib.add_state() is None


def test_add_missing_results_uncertain_failed_already(env):
    add_env(env)
    new1, new2 = str(env.base / "new1.jpg"), str(env.base / "sub" / "new2.arw")
    env.lr.import_status = {new1: "already", new2: "uncertain"}
    env.lib.add_missing()
    c = env.lib.add_state()["counts"]
    assert c == {"added": 1, "uncertain": 1, "failed": 0, "pending": 0}
    assert [p["name"] for p in env.lib.add_state()["problems"]] == ["new2.arw"]
    assert env.lr.imported.count(new2) == 1                                    # uncertain 不重复添加

    def refuse(path, fn, sleep=None):
        return {"lr": "failed", "reason": "Lightroom 拒绝了该文件：x"}
    env.lib._add_fn = refuse
    env.lib.close_add()
    env.lib.add_missing()
    assert env.lib.add_state()["counts"]["failed"] == 2


def test_add_missing_busy_retry_comes_from_importer(env):
    add_env(env)
    calls = []
    new1 = str(env.base / "new1.jpg")

    def flaky(path):
        calls.append(path)
        if path == new1 and calls.count(new1) < 3:
            raise RuntimeError("现在不能写入，Lightroom 正忙")
        return {"status": "imported"}
    env.lr.import_photo = flaky
    env.lib._add_fn = imp.add_to_lightroom
    env.lib.add_missing()
    assert env.lib.add_state()["counts"]["added"] == 2 and calls.count(new1) == 3


def test_add_missing_refusals(env):
    add_env(env)
    env.lr.readonly = "只读开关开着"
    r = env.lib.add_missing()
    assert r["ok"] is False and "只读模式已开启" in r["message"] and env.lr.imported == []
    env.lr.readonly = None
    env.lr.connected = False
    assert env.lib.add_missing() == {"ok": False, "message": "Lightroom 未连接，无法显示照片信息"}
    env.lr.connected = True
    env.lib._busy_fn = lambda: True
    assert "正在导入" in env.lib.add_missing()["message"]
    env.lib._busy_fn = lambda: False
    assert env.lr.imported == []


def test_add_missing_nothing_to_add_and_already_running(env):
    seed(env)
    env.lib.refresh_sync()
    assert env.lib.add_missing() == {"ok": False, "message": "没有需要加入 Lightroom 的照片。"}
    touch(env.base / "new1.jpg")
    touch(env.base / "sub" / "new2.arw")
    env.lib.refresh_sync()
    assert env.lib.state()["not_added"] == 2
    env.lib._run_async = lambda fn: None                                       # 不执行后台线程：保持“正在加入”
    assert env.lib.add_missing()["ok"] is True
    assert env.lib.add_state()["state"] == "running"
    assert "正在加入" in env.lib.add_missing()["message"]
    assert env.lib.cancel_add() == {"ok": True}


def test_add_missing_cancel_stops_before_next(env):
    add_env(env)

    def first_then_cancel(path, fn, sleep=None):
        env.lib.cancel_add()
        return {"lr": "imported", "reason": ""}
    env.lib._add_fn = first_then_cancel
    env.lib.add_missing()
    s = env.lib.add_state()
    assert s["cancelled"] is True and s["counts"]["added"] == 1 and s["state"] == "done"


def test_add_missing_lightroom_disconnects_midway_and_vanished_file(env):
    add_env(env)
    new1, new2 = env.base / "new1.jpg", env.base / "sub" / "new2.arw"
    os.remove(new1)                                                            # 扫描后文件被删
    env.lib.add_missing()
    s = env.lib.add_state()
    assert s["counts"]["failed"] == 1 and s["problems"][0]["reason"] == "文件已不存在。" and s["counts"]["added"] == 1
    # 断开：不再逐张尝试
    env.lib.close_add()
    touch(new1)
    env.lr.catalog = [c for c in env.lr.catalog]
    env.lib.refresh_sync()
    env.lib._add_fn = lambda path, fn, sleep=None: (setattr(env.lr, "connected", False) or {"lr": "imported", "reason": ""})
    env.lr.imported.clear()
    env.lib.add_missing()
    c = env.lib.add_state()["counts"]
    assert c["added"] == 1 and c["pending"] == 1 and env.lib.add_state()["problems"][0]["lr"] == "pending"       # 断开后不再逐张尝试


# ---------------------------------------------------------------- 与导入完成事件、Api 的联动与参数校验
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    base = tmp_path / "lib"
    base.mkdir()
    a._settings.data["base_folder"] = str(base)
    a._photolib.lr = FakeLr()
    a._photolib._run_async = lambda fn: fn()
    a._photolib.server.port = 5555
    a._base = base
    yield a
    a._shutdown()


def test_api_import_done_event_refreshes_library(api):
    api._photolib.lr.catalog = []
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api._emit({"type": "import_done", "counts": {}})                           # 导入完成事件 -> 刷新图库
    s = api.library_state()
    assert s["state"] == "ready" and s["total"] == 1
    n = len(api._photolib.lr.list_calls)
    api._emit({"type": "import_progress", "i": 1})                             # 其他事件不触发刷新
    api._emit({"type": "preview", "state": "ok"})
    assert len(api._photolib.lr.list_calls) == n


def test_api_reconnect_refreshes_library(api):
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api._emit({"type": "status", "connected": True})
    assert api.library_state()["state"] == "ready"
    assert api.library_state()["total"] == 1


def test_api_gallery_picker_changes_browsing_only(api, tmp_path):
    browse = tmp_path / "existing"
    browse.mkdir()
    touch(browse / "B.jpg")
    api._photolib.lr.catalog = [cat(2, browse / "B.jpg")]
    api.choose_folder = lambda start="": {"ok": True, "path": str(browse)}
    assert api.gallery_pick_folder()["ok"]
    assert api._settings.data["base_folder"] == str(api._base)
    assert api.library_state()["base"] == str(browse)
    assert api.library_state()["total"] == 1


def test_api_lightroom_selection_event_updates_library(api):
    touch(api._base / "A.jpg")
    touch(api._base / "B.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg"), cat(2, api._base / "B.jpg")]
    api.library_refresh()
    api._emit({"type": "selection", "count": 1, "active_id": "102", "photos": [{"id": "102", "name": "B.jpg"}]})
    assert api.library_state()["selection"] == {"ids": ["102"], "active": "102"}


def test_api_pick_apply_done_refreshes_rating_and_flag(api):
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api.library_refresh()
    api._photolib.lr.meta = {"101": {"rating": 4, "flag": "pick"}}
    api._emit({"type": "pick_apply_done", "stage": "done", "results": [{"photo_id": "101", "status": "ok"}]})
    end = time.time() + 3
    while time.time() < end and api.library_state()["photos"][0]["rating"] != 4:
        time.sleep(0.02)
    p = api.library_state()["photos"][0]
    assert (p["rating"], p["flag"]) == (4, "pick")


def test_api_adjust_undo_restore_invalidate_thumbnails(api):
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api.library_refresh()
    api.library_thumbnails(["101"])
    api._photolib.process_thumbs_once()
    assert "101" in api.library_state()["thumbs"]
    api._lib_applied("E1", "101", "预设", [])                                  # 软件自己套用预设
    assert "101" not in api.library_state()["thumbs"]
    api._photolib.clock = api._photolib._clock                                  # （保持真实时钟：失效后等 1 秒再重取）
    api._photolib._dirty.clear()
    api.library_thumbnails(["101"])
    api._photolib.process_thumbs_once()
    assert "101" in api.library_state()["thumbs"]
    api._backend.photo = {"id": "101", "name": "A.jpg"}
    api._lr.undo = lambda eid, force=False: {"ok": True, "conflict": False, "message": ""}
    api._lr.restore_original = lambda force=False: {"ok": True, "conflict": False, "message": "", "result": {"edits_undone": []}}
    api.undo("E1")
    assert "101" not in api.library_state()["thumbs"]
    api._photolib._dirty.clear()
    api.library_thumbnails(["101"])
    api._photolib.process_thumbs_once()
    api.restore_original()
    assert "101" not in api.library_state()["thumbs"]


def test_api_tracker_change_invalidates_current_photo(api):
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api.library_refresh()
    api.library_thumbnails(["101"])
    api._photolib.process_thumbs_once()
    api._backend.photo = {"id": "101", "name": "A.jpg"}
    api._tracker.observe = lambda ev: True                                     # 假装 AI 调整改变了表格
    api._on_event({"type": "tool", "name": "lr_set_develop"})
    assert "101" not in api.library_state()["thumbs"]


def test_api_signatures_take_no_paths(api):
    assert list(inspect.signature(api.library_state).parameters) == []
    assert list(inspect.signature(api.library_refresh).parameters) == []
    assert list(inspect.signature(api.library_thumbnails).parameters) == ["ids", "retry"]
    assert list(inspect.signature(api.library_select).parameters) == ["ids", "active"]
    for n in ("library_add_missing", "library_cancel_add", "library_close_add", "library_clear_selection"):
        assert list(inspect.signature(getattr(api, n)).parameters) == []


def test_api_validates_page_values(api):
    touch(api._base / "A.jpg")
    api._photolib.lr.catalog = [cat(1, api._base / "A.jpg")]
    api.library_refresh()
    for bad in (None, 5, "101", {"a": 1}, [], [None], [["101"]], ["101", "999"], ["x" * 65], ["a b"], ["101;"], [101]):
        r = api.library_select(bad)
        assert r["ok"] is False and r["status"] == "refused"
    assert api._photolib.lr.select_calls == []
    for bad in (None, 5, "101", [5], ["../etc"], ["999"], ["x"] * 201):
        assert api.library_thumbnails(bad)["ok"] is False
    assert api.library_thumbnails(["101"], retry="yes")["ok"] is True          # retry 只认 True
    assert api.library_select(["101"], {"x": 1})["status"] == "refused"
    r = api.library_select(["101"], "101")
    assert r["ok"] is True and api._photolib.lr.select_calls == [(["101"], "101", None)]


def test_api_start_refresh_and_thumb_server_lifecycle(api):
    assert api._photolib.server.store is not api._preview.server.store          # 缩略图有自己的缓存，不挤占中栏预览的缓存
    assert api._photolib.store.max_bytes == 64 * 1024 * 1024 and api._photolib.store._max_cache == 500


def test_lrservice_library_wrappers_use_injected_service():
    from lr_service import LrService
    calls = []

    class Svc:
        def list_folder_photos(self, path, recursive, offset, limit):
            calls.append(("list", path, recursive, offset, limit))
            return {"in_catalog": True, "total": 0, "photos": []}

        def get_thumbnails(self, ids, size):
            calls.append(("thumbs", ids, size))
            return {"thumbnails": []}

        def select_photos(self, ids, active, show_folder):
            calls.append(("select", ids, active, show_folder))
            return {"status": "selected"}
    lr = LrService(library_service=Svc())
    lr.library_list("D:\\x", 500, 500)
    lr.library_thumbnails(["1"], 256)
    lr.library_select(["1"], "1", "D:\\x")
    assert calls == [("list", "D:\\x", True, 500, 500), ("thumbs", ["1"], 256), ("select", ["1"], "1", "D:\\x")]
