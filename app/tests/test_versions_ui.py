# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""多版本页（界面直接触发）：差异由后端记住、页面只回传一次性令牌；AI 忙时拒绝写入；版本名在后端校验；只读开关。
全部用假对象：不开窗口、不连真实 Lightroom / AI。"""
from types import SimpleNamespace

import pytest

import main
from lr_service import LrService


class FakeEdits:
    def __init__(self):
        self.photo = "photo-1234"
        self.current = {"Exposure2012": 0.0}
        self.saved = {"Exposure2012": 0.2}
        self.applied = False
        self.saved_calls = []
        self.versions = SimpleNamespace(
            get=lambda photo, name: {"name": name, "settings": dict(self.saved)},
            thumbnail_path=lambda photo, name: None,
        )

    def photo_id_of(self, photo):
        return self.photo, "test.DNG"

    def call(self, command, params, timeout):
        return {"settings": self.current.copy()}

    @staticmethod
    def _same(a, b):
        return a == b

    def apply_version(self, name, photo):
        self.applied = True
        return {"edit_id": "20261109-120000-ab12", "photo_id": self.photo,
                "changes": [{"parameter": "Exposure2012", "before": 0.0, "after": 0.2}]}

    def save_version(self, name, note, photo, thumbnail):
        self.saved_calls.append((name, photo, thumbnail))
        return {"version": name, "photo_id": self.photo}


# ---------------------------------------------------------------- LrService：一致性校验（PR #7 原有）
def test_version_apply_rejects_changed_photo_and_settings():
    edits = FakeEdits()
    service = LrService(edit_service=edits)
    plan = service.version_record("warm")
    assert plan["ok"] and plan["result"]["changed"] == ["Exposure2012"]

    edits.photo = "photo-5678"
    assert not service.apply_version("warm", "photo-1234", plan["result"]["current"], plan["result"]["target"])["ok"]
    edits.photo = "photo-1234"
    edits.current["Exposure2012"] = 0.1
    assert not service.apply_version("warm", "photo-1234", plan["result"]["current"], plan["result"]["target"])["ok"]
    assert not edits.applied


def test_version_apply_uses_existing_edit_service():
    edits = FakeEdits()
    service = LrService(edit_service=edits)
    assert service.apply_version("warm", "photo-1234", {"Exposure2012": 0.0}, {"Exposure2012": 0.2})["ok"]
    assert edits.applied


def test_version_apply_rejects_replaced_saved_version():
    edits = FakeEdits()
    service = LrService(edit_service=edits)
    result = service.apply_version("warm", "photo-1234", {"Exposure2012": 0.0}, {"Exposure2012": 0.3})
    assert not result["ok"] and not edits.applied


def test_save_version_survives_a_failed_thumbnail_and_uses_that_photo():
    edits = FakeEdits()
    service = LrService(edit_service=edits)                         # 没有 Bridge：取预览图会出错
    assert service.save_version("warm")["ok"]
    assert edits.saved_calls == [("warm", "photo-1234", None)]      # 版本照样保存；照片用已解析出的 id


# ---------------------------------------------------------------- Api：令牌、门控、校验
class Session:
    busy = False


def make_api(edits=None):
    api = main.Api.__new__(main.Api)
    api._edits_fake = edits or FakeEdits()
    api._lr = LrService(edit_service=api._edits_fake)
    api._version_pending = None
    api._busy, api._session = False, Session()
    api._applied = []
    api._lib_applied = lambda *a: api._applied.append(a)
    return api


def test_plan_gives_display_rows_and_a_token_but_no_raw_settings():
    api = make_api()
    r = api.version_plan("warm")
    assert r["ok"]
    d = r["result"]
    assert set(d) == {"photo_id", "name", "count", "items", "token"}
    assert d["count"] == 1 and d["items"] == [{"label": "曝光", "before": "0", "after": "0.2"}]
    assert isinstance(d["token"], str) and len(d["token"]) >= 12
    assert api._version_pending["current"] == {"Exposure2012": 0.0}  # 参数字典留在后端
    assert api._version_pending["target"] == {"Exposure2012": 0.2}


def test_apply_takes_only_the_token_and_it_is_single_use():
    api = make_api()
    token = api.version_plan("warm")["result"]["token"]
    r = api.version_apply(token)
    assert r["ok"] and api._edits_fake.applied
    assert api._applied == [("20261109-120000-ab12", "photo-1234", "版本：warm",
                             [{"key": "Exposure2012", "before": 0.0, "after": 0.2}])]
    api._edits_fake.applied = False
    again = api.version_apply(token)
    assert again["ok"] is False and again["stale"] is True and not api._edits_fake.applied


@pytest.mark.parametrize("bad", [None, "", "x", 5, {"token": "x"}, ["x"]])
def test_apply_rejects_missing_or_wrong_tokens(bad):
    api = make_api()
    assert api.version_apply(bad)["ok"] is False                    # 还没预演过
    api.version_plan("warm")
    assert api.version_apply(bad)["ok"] is False
    assert not api._edits_fake.applied
    assert api._version_pending is None                             # 用错一次就作废，必须重新查看


def test_a_newer_plan_invalidates_the_older_token():
    api = make_api()
    old = api.version_plan("warm")["result"]["token"]
    new = api.version_plan("cool")["result"]["token"]
    assert new != old
    assert api.version_apply(old)["ok"] is False and not api._edits_fake.applied


def test_apply_checks_against_what_the_backend_showed_not_what_the_page_says():
    api = make_api()
    token = api.version_plan("warm")["result"]["token"]
    api._edits_fake.current["Exposure2012"] = 0.1                   # 预演之后照片被改了
    r = api.version_apply(token)
    assert r["ok"] is False and "重新查看" in r["message"] and not api._edits_fake.applied
    token = api.version_plan("warm")["result"]["token"]
    api._edits_fake.saved["Exposure2012"] = 0.5                     # 预演之后版本被覆盖了
    assert api.version_apply(token)["ok"] is False and not api._edits_fake.applied
    token = api.version_plan("warm")["result"]["token"]
    api._edits_fake.photo = "photo-5678"                            # 预演之后换了照片
    assert api.version_apply(token)["ok"] is False and not api._edits_fake.applied


def test_version_writes_are_refused_while_ai_is_working():
    api = make_api()
    token = api.version_plan("warm")["result"]["token"]
    api._busy = True
    for r in (api.version_apply(token), api.version_save("warm")):
        assert r["ok"] is False and r["busy"] is True and "AI 正在处理" in r["message"]
    assert not api._edits_fake.applied and api._edits_fake.saved_calls == []
    api._busy, api._session.busy = False, True
    assert api.version_save("warm")["ok"] is False
    assert api.version_plan("warm")["ok"] is True                   # 只读的查看不受影响


@pytest.mark.parametrize("bad", ["", "   ", None, 5, "a" * 41, "a\nb", "a\x00b", ["warm"]])
def test_version_names_are_validated_in_the_backend(bad):
    api = make_api()
    api._preview = None                                             # 校验不过就不会用到预览服务
    for r in (api.version_save(bad), api.version_plan(bad), api.version_preview(bad)):
        assert r["ok"] is False and "版本名" in r["message"]
    assert api._edits_fake.saved_calls == [] and api._version_pending is None


def test_version_save_trims_the_name():
    api = make_api()
    assert api.version_save("  暖色调  ")["ok"]
    assert api._edits_fake.saved_calls[0][0] == "暖色调"


class ReadOnlyError(RuntimeError):
    pass


def test_readonly_switch_refuses_apply_with_plain_message():
    edits = FakeEdits()

    def refuse(name, photo):
        raise ReadOnlyError("只读模式已开启，不允许修改照片。要关闭它：删除文件 C:\\Users\\x\\LrMcp\\readonly")
    edits.apply_version = refuse
    api = make_api(edits)
    r = api.version_apply(api.version_plan("warm")["result"]["token"])
    assert r["ok"] is False and r["readonly"] is True
    assert r["message"] == "只读模式已开启，不允许修改照片。要修改，请先关闭只读模式。"
    assert api._applied == []
