# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""批量复用单张调整（界面直接触发的写入）：只认最近一次预演的计划、AI 忙时拒绝、参数在后端校验、整批还原只认自己执行过的批次。
全部用假对象：不开窗口、不连真实 Lightroom / AI。"""
import pytest

import main
from lr_service import LrService

EDIT, BATCH = "20261109-120000-ab12", "20261109-120500-cd34"


class FakeLr:
    def __init__(self):
        self.calls = []
        self.undo_problems = []

    def batch_plan_from_edit(self, edit_id):
        self.calls.append(("plan", edit_id))
        return {"ok": True, "result": {"plan_id": "plan-1", "will_change": 1, "skipped": 0, "source_photo": "A.ARW",
                                       "deltas": {"Exposure2012": 0.1, "Contrast2012": -5}, "skipped_parameters": ["CropAngle"],
                                       "photos": [{"photo": "B.ARW", "photo_id": "photo-1234", "will_change": True,
                                                   "changes": [{"parameter": "Exposure2012", "before": 0.0, "after": 0.1}]}]}}

    def batch_apply(self, plan_id):
        self.calls.append(("apply", plan_id))
        return {"ok": True, "result": {"changed": 1, "batch_id": BATCH, "results": []}}

    def undo(self, edit_id, force=False):
        self.calls.append(("undo", edit_id))
        return {"ok": True, "conflict": False, "result": {"problems": list(self.undo_problems)}, "message": ""}


class Quiet:
    def request(self, *a):
        pass


class Session:
    busy = False


def make_api():
    api = main.Api.__new__(main.Api)
    api._lr = FakeLr()
    api._batch_pending, api._batch_photo_ids, api._batch_done = "", [], set()
    api._busy, api._session = False, Session()
    api._preview = Quiet()
    api._thumbs_stale = lambda *ids: None
    return api


def test_batch_apply_requires_the_latest_previewed_plan():
    api = make_api()
    assert not api.batch_apply("plan-1")["ok"]
    assert api.batch_plan_from_edit(EDIT)["ok"]
    assert api._batch_photo_ids == ["photo-1234"]
    assert not api.batch_apply("other-plan")["ok"]
    assert api.batch_apply("plan-1")["ok"]
    assert not api.batch_apply("plan-1")["ok"]                      # 一次性
    assert api._lr.calls == [("plan", EDIT), ("apply", "plan-1")]


def test_plan_rows_carry_plain_names_and_formatted_values():
    api = make_api()
    plan = api.batch_plan_from_edit(EDIT)["result"]
    change = plan["photos"][0]["changes"][0]
    assert change["label"] == "曝光" and change["before_text"] == "0" and change["after_text"] == "0.1"
    assert plan["skipped_labels"] == ["拉直角度"]
    assert plan["delta_items"] == [{"label": "曝光", "delta": "+0.1"}, {"label": "对比度", "delta": "-5"}]


@pytest.mark.parametrize("bad", ["", None, 5, "edit-1", "../../x", "20261109-120000-ab12.json", ["20261109-120000-ab12"]])
def test_plan_rejects_malformed_edit_ids_before_touching_lightroom(bad):
    api = make_api()
    r = api.batch_plan_from_edit(bad)
    assert r["ok"] is False and r["message"] and api._lr.calls == []


@pytest.mark.parametrize("bad", [None, 5, ["plan-1"], {"plan_id": "plan-1"}, ""])
def test_apply_rejects_non_string_plan_ids(bad):
    api = make_api()
    assert api.batch_plan_from_edit(EDIT)["ok"]
    assert api.batch_apply(bad)["ok"] is False
    assert ("apply", "plan-1") not in api._lr.calls


@pytest.mark.parametrize("how", ["chat_or_pick", "session"])
def test_every_batch_write_is_refused_while_ai_is_working(how):
    api = make_api()
    assert api.batch_plan_from_edit(EDIT)["ok"]
    api._batch_done.add(BATCH)
    if how == "chat_or_pick":
        api._busy = True                                            # 对话、AI 挑片、“记成经验”共用这个标记
    else:
        api._session.busy = True                                    # 来源自己报告正在处理一轮
    before = list(api._lr.calls)
    for r in (api.batch_plan_from_edit(EDIT), api.batch_apply("plan-1"), api.batch_undo(BATCH)):
        assert r["ok"] is False and r["busy"] is True and "AI 正在处理" in r["message"]
    assert api._lr.calls == before                                  # 没有任何调用到达 Lightroom


def test_busy_refusal_keeps_the_previewed_plan_usable():
    api = make_api()
    assert api.batch_plan_from_edit(EDIT)["ok"]
    api._busy = True
    assert api.batch_apply("plan-1")["ok"] is False
    api._busy = False
    assert api.batch_apply("plan-1")["ok"] is True                  # AI 忙完后不用重新预演


def test_batch_undo_only_accepts_batches_this_session_applied():
    api = make_api()
    assert api.batch_undo(BATCH)["ok"] is False                     # 没执行过的批次
    assert api.batch_undo(EDIT)["ok"] is False                      # 任意一条修改记录也不行
    for bad in (None, 5, "../x", ""):
        assert api.batch_undo(bad)["ok"] is False
    assert api._lr.calls == []
    assert api.batch_plan_from_edit(EDIT)["ok"] and api.batch_apply("plan-1")["ok"]
    api._lr.undo_problems = [{"edit_id": "x", "error": "冲突"}]
    assert api.batch_undo(BATCH)["ok"] is True and BATCH in api._batch_done      # 没还原完：还可以再点一次
    api._lr.undo_problems = []
    assert api.batch_undo(BATCH)["ok"] is True and BATCH not in api._batch_done
    assert api.batch_undo(BATCH)["ok"] is False                     # 已整批还原：不能重复


# ---------------------------------------------------------------- 只读开关（由 server 的 EditService 拦截，这里确认界面拿到大白话）
class ReadOnlyError(RuntimeError):
    pass


class ReadOnlyEdits:
    def batch_plan_from_edit(self, edit_id, photos):
        raise ReadOnlyError("只读模式已开启，不允许修改照片。要关闭它：删除文件 C:\\Users\\x\\LrMcp\\readonly")

    def batch_apply(self, plan_id):
        raise ReadOnlyError("只读模式已开启，不允许修改照片。要关闭它：删除文件 C:\\Users\\x\\LrMcp\\readonly")


def test_readonly_switch_refuses_batch_with_plain_message():
    svc = LrService(edit_service=ReadOnlyEdits())
    for r in (svc.batch_plan_from_edit(EDIT), svc.batch_apply("plan-1")):
        assert r["ok"] is False and r["readonly"] is True
        assert r["message"] == "只读模式已开启，不允许修改照片。要修改，请先关闭只读模式。"
        assert "C:\\" not in r["message"]                           # 不把本机路径带到界面


# ---------------------------------------------------------------- 套用预设、撤销、还原：同样的“AI 忙时拒绝”
class FakeLib:
    def __init__(self):
        self.calls = []

    def apply_prepare(self, kind, ref, strength=100):
        self.calls.append("prepare")
        return {"ok": True, "token": "t"}

    def apply_confirm(self, token):
        self.calls.append("confirm")
        return {"ok": True}


class FakeLr2(FakeLr):
    def restore_original(self, force=False):
        self.calls.append(("restore_original",))
        return {"ok": False, "conflict": False, "message": ""}


@pytest.mark.parametrize("how", ["chat_or_pick", "session"])
def test_preset_apply_undo_restore_are_refused_while_ai_is_working(how):
    api = make_api()
    api._lr, api._lib = FakeLr2(), FakeLib()
    if how == "chat_or_pick":
        api._busy = True
    else:
        api._session.busy = True
    for r in (api.lib_apply_prepare("mine", "p1"), api.lib_apply_confirm("t"), api.undo(EDIT), api.restore_original()):
        assert r["ok"] is False and r["busy"] is True and "AI 正在处理" in r["message"]
    assert api._lib.calls == [] and api._lr.calls == []              # 没有任何调用到达 Lightroom / 预设服务
    api._busy, api._session.busy = False, False
    assert api.lib_apply_prepare("mine", "p1")["ok"] and api.lib_apply_confirm("t")["ok"]      # 空闲时照常
    assert api._lib.calls == ["prepare", "confirm"]


def test_ai_side_writes_do_not_go_through_the_page_busy_check():
    """AI 自己发起的写入经确认服务（confirm_hub），与 Api._write_block 无关：busy 时确认服务照常工作。"""
    import inspect

    import confirm_hub
    assert "_write_block" not in inspect.getsource(confirm_hub)
