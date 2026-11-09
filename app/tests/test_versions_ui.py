# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
from types import SimpleNamespace

from lr_service import LrService


class FakeEdits:
    def __init__(self):
        self.photo = "photo-1234"
        self.current = {"Exposure2012": 0.0}
        self.applied = False
        self.versions = SimpleNamespace(
            get=lambda photo, name: {"name": name, "settings": {"Exposure2012": 0.2}},
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
        return {"edit_id": "edit-1"}


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
