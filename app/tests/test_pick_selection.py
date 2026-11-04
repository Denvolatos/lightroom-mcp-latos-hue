# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 挑片第 1 步：读取 Lightroom 当前全部选中的照片（只读）。"""
import backend as be
from adjustments import AdjustmentTracker
from lr_service import LrService


class FakeBridge:
    def __init__(self, reply=None, connected=True, boom=False):
        self.reply, self.connected, self.boom = reply, connected, boom
        self.calls = []

    def call(self, cmd, params=None, timeout=30):
        self.calls.append((cmd, params))
        if self.boom:
            raise RuntimeError("x")
        return self.reply


def photos(n):
    return [{"id": f"P{i}", "name": f"IMG_{i}.ARW", "rating": i % 6, "flag": "none", "camera": "x", "iso": "100"} for i in range(n)]


def test_selected_all_reads_only_needed_fields_with_one_call():
    b = FakeBridge({"count": 3, "active_id": "P1", "photos": photos(3)})
    r = LrService(bridge=b, edit_service=object()).selected_all()
    assert r["count"] == 3 and r["active_id"] == "P1"
    assert r["photos"][0] == {"id": "P0", "name": "IMG_0.ARW", "rating": 0, "flag": "none"}
    assert b.calls == [("list_selected", {"limit": 20})]


def test_selected_all_limit_is_capped_and_failures_return_none():
    b = FakeBridge({"count": 0, "photos": []})
    LrService(bridge=b, edit_service=object()).selected_all(limit=999)
    assert b.calls[0][1] == {"limit": 20}
    assert LrService(bridge=FakeBridge(connected=False), edit_service=object()).selected_all() is None
    assert LrService(bridge=FakeBridge(boom=True), edit_service=object()).selected_all() is None


def test_selected_all_nothing_selected_and_bad_count():
    r = LrService(bridge=FakeBridge({"count": 0, "photos": []}), edit_service=object()).selected_all()
    assert r == {"count": 0, "active_id": None, "photos": []}
    r = LrService(bridge=FakeBridge({"count": "x", "photos": photos(2) + ["junk", {"name": "no id"}]}), edit_service=object()).selected_all()
    assert r["count"] == 2 and len(r["photos"]) == 2


class AllLr:
    connected = True
    plugin_version = "0.15.0"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def selected_all(self, limit=20):
        self.calls += 1
        return self.reply


class Sess:
    alive, busy, spawned_at = True, False, 0.0


def make(reply):
    events = []
    lr = AllLr(reply)
    b = be.Backend(lr, Sess(), AdjustmentTracker(), events.append, state_file=None, cleaner=lambda: None)
    return b, lr, events


def test_backend_one_poll_gives_photo_and_selection_and_emits_only_on_change():
    sel = {"count": 3, "active_id": "P1", "photos": [{"id": f"P{i}", "name": f"N{i}", "rating": 0, "flag": "none"} for i in range(3)]}
    b, lr, events = make(sel)
    b.refresh_photo()
    assert lr.calls == 1                                           # 同一次调用里得到两样东西
    assert b.photo == {"id": "P1", "name": "N1"}
    ev = [e for e in events if e["type"] == "selection"]
    assert len(ev) == 1 and ev[0]["count"] == 3 and [p["name"] for p in ev[0]["photos"]] == ["N0", "N1", "N2"]
    b.refresh_photo()
    assert len([e for e in events if e["type"] == "selection"]) == 1   # 没变化不重复推送
    lr.reply = {**sel, "count": 4}
    b.refresh_photo()
    assert len([e for e in events if e["type"] == "selection"]) == 2
    assert b.selection_public()["count"] == 4


def test_backend_nothing_selected():
    b, lr, events = make({"count": 0, "active_id": None, "photos": []})
    b.refresh_photo()
    assert b.photo == {"id": None, "name": None} and b.selection_public() == {"count": 0, "active_id": None, "photos": []}


def test_backend_unreadable_keeps_previous():
    b, lr, events = make({"count": 1, "active_id": "P0", "photos": [{"id": "P0", "name": "A", "rating": 0, "flag": "none"}]})
    b.refresh_photo()
    lr.reply = None
    b.refresh_photo()
    assert b.photo["id"] == "P0" and b.selection_public()["count"] == 1
