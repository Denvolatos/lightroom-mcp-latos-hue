# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""确认卡片带上目标照片（1.1.1）：原值按目标照片读；目标不是当前照片时醒目提示。"""
import threading

import confirm_hub as ch

SET = "mcp__lightroom_mcp__lr_set_develop"


class FakeLr:
    """只提供 confirm_hub 用到的只读接口（与 lr_service.LrService 同名）。"""

    def __init__(self, selected=("A1111111", "a.jpg")):
        self.sel = selected
        self.read = []

    def selected_photo(self):
        return {"id": self.sel[0], "name": self.sel[1]} if self.sel else None

    def current_values(self, keys):
        self.read.append("selected")
        return {k: 0.1 for k in keys}

    def develop_of(self, photo_id):
        self.read.append(photo_id)
        return {"photo": {"id": photo_id, "name": "b.jpg"}, "settings": {"Exposure2012": 0.7}, "hsl": {}}


def card_for(lr, tool_input, tool=SET):
    cards = []
    hub = ch.ConfirmHub(cards.append, timeout=5, current_values=lr.current_values if lr else None)

    def emit(ev):
        cards.append(ev)
        if ev["type"] == "confirm":
            hub.answer(ev["id"], False)
    hub.emit = emit
    t = threading.Thread(target=hub.request, args=(tool, tool_input))
    t.start()
    t.join(5)
    return next(c for c in cards if c["type"] == "confirm")


def test_selected_target_shows_current_photo_name():
    lr = FakeLr()
    c = card_for(lr, {"changes": {"Exposure2012": 0.3}})
    assert c["photo_id"] == "A1111111" and c["photo_name"] == "a.jpg" and c["photo_is_current"] is True
    assert "a.jpg" in c["title"] and "warning" not in c
    assert c["items"][0]["from"] == "0.1" and lr.read == ["selected"]


def test_other_photo_reads_that_photo_and_warns():
    lr = FakeLr()
    c = card_for(lr, {"changes": {"Exposure2012": 0.9}, "photo": "B2222222"})
    assert c["photo_id"] == "B2222222" and c["photo_name"] == "b.jpg" and c["photo_is_current"] is False
    assert "非当前照片" in c["title"] and "b.jpg" in c["warning"]
    assert c["items"][0]["from"] == "0.7"                    # 原值是目标照片的，不是当前选中那张的
    assert lr.read == ["B2222222"]


def test_explicit_id_equal_to_current_is_not_warned():
    c = card_for(FakeLr(), {"changes": {"Exposure2012": 0.3}, "photo": "A1111111"})
    assert c["photo_is_current"] is True and "warning" not in c


def test_restore_original_on_other_photo_warns():
    c = card_for(FakeLr(), {"photo": "B2222222"}, tool="mcp__lightroom_mcp__lr_restore_original")
    assert c["photo_is_current"] is False and "warning" in c


def test_no_lightroom_keeps_old_card():
    c = card_for(None, {"changes": {"Exposure2012": 0.3}})
    assert "photo_id" not in c and c["title"] == "拟调整" and c["items"][0]["from"] == "—"


def test_non_dict_changes_do_not_break_the_card():
    c = card_for(FakeLr(), {"changes": '{"Exposure2012": 0.3}'})
    assert c["items"] == []
