# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import main


class FakeLr:
    def __init__(self):
        self.calls = []

    def batch_plan_from_edit(self, edit_id):
        self.calls.append(("plan", edit_id))
        return {"ok": True, "result": {"plan_id": "plan-1", "photos": [
            {"photo_id": "photo-1234", "will_change": True}]}}

    def batch_apply(self, plan_id):
        self.calls.append(("apply", plan_id))
        return {"ok": True, "result": {"changed": 0}}


def test_batch_apply_requires_the_latest_previewed_plan():
    api = main.Api.__new__(main.Api)
    api._lr = FakeLr()
    api._batch_pending = ""
    api._batch_photo_ids = []
    assert not api.batch_apply("plan-1")["ok"]
    assert api.batch_plan_from_edit("edit-1")["ok"]
    assert api._batch_photo_ids == ["photo-1234"]
    assert not api.batch_apply("other-plan")["ok"]
    assert api.batch_apply("plan-1")["ok"]
    assert not api.batch_apply("plan-1")["ok"]
    assert api._lr.calls == [("plan", "edit-1"), ("apply", "plan-1")]
