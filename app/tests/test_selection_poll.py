# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""切换照片提速（1.1.1）：Backend 与 PreviewManager 共用一次选区轮询（约每秒），换照片时预览立即开始取图，
选区没变不调 get_develop；refresh_photo 加锁并丢弃回得慢的旧结果；选区轮询不再阻塞 tick。全部用假对象。"""
import threading
import time

import backend as be
import preview as pv
from adjustments import AdjustmentTracker
from lr_service import LrService
from preview import PreviewManager, PreviewServer, PreviewStore


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def sel(aid, *ids):
    ids = ids or (aid,)
    return {"count": len(ids), "active_id": aid,
            "photos": [{"id": i, "name": f"{i}.ARW", "rating": 0, "flag": "none"} for i in ids],
            "info": {i: {"id": i, "name": f"{i}.ARW", "camera": "Sony X", "iso": "ISO 100"} for i in ids}}


class Lr:
    """选区、调整参数与预览都计数。"""
    connected = True
    plugin_version = "x"

    def __init__(self):
        self.reply = sel("P1")
        self.calls = {"list": 0, "detail": 0, "develop": 0, "preview": 0}
        self.exposure = {}

    def selected_all_info(self, limit=20):
        self.calls["list"] += 1
        return self.reply

    def selected_detail(self):
        self.calls["detail"] += 1
        aid = self.reply["active_id"]
        return {"id": aid, "name": f"{aid}.ARW", "info": self.reply["info"].get(aid, {})}

    def develop_of(self, pid):
        self.calls["develop"] += 1
        return {"settings": {"Exposure2012": self.exposure.get(pid, 0)}, "hsl": {}, "has_local_adjustments": False}

    def preview_bytes(self, pid, edge):
        self.calls["preview"] += 1
        return b"\xff\xd8" + pid.encode(), "x"


class Sess:
    alive, busy, spawned_at = True, False, 0.0

    def ensure_running(self):
        return True


def make():
    lr, clock, events = Lr(), Clock(), []
    server = PreviewServer(PreviewStore())
    server.port = 1
    m = PreviewManager(lr, server, events.append, clock=clock)
    b = be.Backend(lr, Sess(), AdjustmentTracker(), events.append, state_file=None, clock=clock, cleaner=lambda: None,
                   previews=m)
    return b, m, lr, clock, events


def oks(events):
    return [e for e in events if e.get("type") == "preview" and e.get("state") == "ok" and not e.get("loading")]


def test_one_list_selected_feeds_both_and_photo_switch_starts_preview_at_once():
    b, m, lr, clock, events = make()
    b.refresh_photo()
    assert lr.calls["list"] == 1 and b.photo["id"] == "P1"
    assert m.process_due()                                                    # 换了照片：立即到期，不等下一次轮询
    assert lr.calls["detail"] == 0                                            # 预览没有再读一次选区
    assert oks(events)[-1]["photo"]["id"] == "P1" and oks(events)[-1]["photo"]["camera"] == "Sony X"
    n = dict(lr.calls)
    for _ in range(5):                                                        # 选区没变：每秒轮询，但不调 get_develop
        clock.t += be.PHOTO_POLL_SECONDS
        b.refresh_photo()
        assert not m.process_due()
    assert lr.calls["develop"] == n["develop"] and lr.calls["preview"] == n["preview"] and lr.calls["list"] == n["list"] + 5
    lr.reply = sel("P2", "P1", "P2")                                          # 在 Lightroom 里换了照片
    clock.t += be.PHOTO_POLL_SECONDS
    b.refresh_photo()
    assert m.process_due() and oks(events)[-1]["photo"]["id"] == "P2" and lr.calls["detail"] == 0


def test_manual_edit_still_found_by_slow_recheck():
    b, m, lr, clock, events = make()
    b.refresh_photo()
    m.process_due()
    m.poll()
    m.process_due()
    lr.exposure["P1"] = 0.3                                                   # 用户在 Lightroom 里手动改了参数
    clock.t += pv.POLL_SECONDS
    b.refresh_photo()                                                         # 轮询刷新了“当前照片”的时间戳
    m.poll()
    assert m.process_due()
    assert lr.calls["detail"] == 0 and oks(events)[-1]["same"] is False


def test_gallery_hint_without_info_then_poll_fills_info_without_refetch():
    b, m, lr, clock, events = make()
    m.show({"id": "P1", "name": "P1.ARW"})                                   # 图库选中：只有名字
    m.process_due()
    assert oks(events)[-1]["photo"]["camera"] is None
    n = dict(lr.calls)
    b.refresh_photo()                                                         # 轮询带来相机、ISO：直接更新信息条
    assert oks(events)[-1]["photo"]["camera"] == "Sony X"
    assert lr.calls["develop"] == n["develop"] and not m.process_due()


def test_stale_hint_falls_back_to_reading_selection():
    b, m, lr, clock, events = make()
    m.show({"id": "P1", "name": "P1.ARW"})
    clock.t += pv.HINT_MAX_AGE + 1                                            # 轮询停了（比如读失败）：不信旧的告知
    m.refresh()
    assert lr.calls["detail"] == 1


def test_result_of_previous_photo_is_not_published_after_switch():
    b, m, lr, clock, events = make()
    orig = lr.preview_bytes

    def slow(pid, edge):
        if pid == "P1":
            m.show({"id": "P2", "name": "P2.ARW"})                           # 取 P1 的途中用户点了 P2
        return orig(pid, edge)
    lr.preview_bytes = slow
    m.show({"id": "P1", "name": "P1.ARW"})
    m.process_due()
    assert [e["photo"]["id"] for e in oks(events)] == []                     # P1 的结果只进缓存，不盖住 P2
    assert m.process_due() and oks(events)[-1]["photo"]["id"] == "P2"


def test_refresh_photo_discards_slow_older_result():
    """两个线程同时读：先发起、后回来的旧结果（P1）不会覆盖新结果（P2）。"""
    events = []
    gate, first_in = threading.Event(), threading.Event()

    class L:
        connected = True
        n = 0

        def selected_all(self, limit=20):
            L.n += 1
            if L.n == 1:
                first_in.set()
                gate.wait(5)
                return sel("P1")
            return sel("P2")
    b = be.Backend(L(), Sess(), AdjustmentTracker(), events.append, state_file=None, cleaner=lambda: None)
    t = threading.Thread(target=b.refresh_photo)
    t.start()
    assert first_in.wait(2)
    b.refresh_photo()
    gate.set()
    t.join(5)
    assert b.photo["id"] == "P2" and b.selection["active_id"] == "P2"
    assert [e["id"] for e in events if e["type"] == "photo"] == ["P2"]


def test_adopt_photo_wins_over_poll_started_before_it():
    events = []
    gate, first_in = threading.Event(), threading.Event()

    class L:
        connected = True

        def selected_all(self, limit=20):
            first_in.set()
            gate.wait(5)
            return sel("OLD")
    b = be.Backend(L(), Sess(), AdjustmentTracker(), events.append, state_file=None, cleaner=lambda: None)
    t = threading.Thread(target=b.refresh_photo)
    t.start()
    assert first_in.wait(2)
    b.adopt_photo("NEW", "NEW.ARW")                                           # 图库刚选中
    gate.set()
    t.join(5)
    assert b.photo == {"id": "NEW", "name": "NEW.ARW"} and b.tracker.current_photo == "NEW"


def test_tick_is_not_blocked_by_selection_poll_once_started():
    class L(Lr):
        def __init__(self):
            super().__init__()
            self.block = threading.Event()

        def selected_all_info(self, limit=20):
            self.calls["list"] += 1
            self.block.wait(5)                                                # 插件队列里排着长命令
            return self.reply
    lr, events = L(), []
    b = be.Backend(lr, Sess(), AdjustmentTracker(), events.append, state_file=None, cleaner=lambda: None)
    b.start()
    try:
        end = time.time() + 3
        while time.time() < end and lr.calls["list"] == 0:
            time.sleep(0.02)
        assert lr.calls["list"] == 1                                          # 轮询线程大约 1 秒内开始读
        t0 = time.monotonic()
        b.tick()                                                              # 状态与自动恢复不等选区读取
        assert time.monotonic() - t0 < 0.5 and lr.calls["list"] == 1
    finally:
        lr.block.set()
        b.stop()


def test_poll_period_is_about_one_second_and_async_refresh_wakes_it():
    assert be.PHOTO_POLL_SECONDS <= 1.0
    lr, events = Lr(), []
    b = be.Backend(lr, Sess(), AdjustmentTracker(), events.append, state_file=None, cleaner=lambda: None)
    b.start()
    try:
        time.sleep(0.1)
        n = lr.calls["list"]
        b.refresh_photo_async()
        end = time.time() + 0.6
        while time.time() < end and lr.calls["list"] == n:
            time.sleep(0.01)
        assert lr.calls["list"] > n                                           # 叫醒后马上读，不等满一个周期
    finally:
        b.stop()


def test_lrservice_selected_all_info_shares_one_call():
    class B:
        connected = True
        calls = 0

        def call(self, cmd, params=None, timeout=30):
            B.calls += 1
            return {"count": 2, "active_id": "P1", "photos": [{"id": "P0", "name": "a"}, {"id": "P1", "name": "b", "iso": "ISO 100"}]}
    lr = LrService(bridge=B(), edit_service=object())
    r = lr.selected_all_info()
    assert B.calls == 1 and r["active_id"] == "P1" and r["count"] == 2 and [p["id"] for p in r["photos"]] == ["P0", "P1"]
    assert r["info"]["P1"]["iso"] == "ISO 100"
