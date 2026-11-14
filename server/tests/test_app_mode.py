# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""LRMCP_APP_MODE=1（由 Latos Hue 启动）时，说明与工具描述只提软件开放的工具；独立使用时保持原样。"""
import asyncio
import re

import pytest

from lightroom_mcp import tools

# 与 app/claude_bridge.py 的 READONLY_TOOLS + ENABLED_WRITE_TOOLS 一致
APP_TOOLS = {"lr_status", "lr_list_selected", "lr_get_develop", "lr_get_preview", "lr_review_selected", "lr_get_metadata",
             "lr_list_presets", "lr_plan_from_edit", "lr_list_versions", "lr_compare", "lr_list_edits", "lr_doctor",
             "lr_set_develop", "lr_restore", "lr_restore_original"}


def _named(text: str) -> set[str]:
    return set(re.findall(r"\blr_[a-z_]+", text or ""))


def _descriptions(server) -> dict[str, str]:
    return {t.name: t.description for t in asyncio.run(server.list_tools())}


def test_standalone_keeps_original_instructions(monkeypatch):
    monkeypatch.delenv(tools.APP_MODE_ENV, raising=False)
    server = tools.build_server(None, "x")
    assert server.instructions == tools.INSTRUCTIONS
    assert "lr_save_version" in server.instructions
    desc = _descriptions(server)
    assert desc["lr_set_develop"] == tools.SET_DESCRIPTION
    assert "lr_batch_set_develop" in desc["lr_plan_from_edit"]


def test_app_mode_mentions_only_enabled_tools(monkeypatch):
    monkeypatch.setenv(tools.APP_MODE_ENV, "1")
    server = tools.build_server(None, "x")
    assert server.instructions == tools.INSTRUCTIONS_APP
    assert _named(server.instructions) <= APP_TOOLS
    desc = _descriptions(server)
    for name in APP_TOOLS:
        assert _named(desc[name]) <= APP_TOOLS, name
    assert "lr_apply_preset" not in desc["lr_set_develop"] and "预设由用户在软件界面里套用" in desc["lr_set_develop"]
    assert "软件界面" in server.instructions and "lr_set_develop" in server.instructions


def _compare_error(monkeypatch, tmp_path) -> str:
    from lightroom_mcp.edits import EditService, EditStore
    from lightroom_mcp.versions import VersionStore

    class Bridge:
        def call(self, command, params=None, timeout=30):
            photo = {"id": "AAAAAAAA-1111", "name": "one.ARW"}
            if command == "list_selected":
                return {"active_id": photo["id"], "count": 1, "photos": [photo]}
            return {"photo": photo, "settings": {}, "has_local_adjustments": False}

    store, versions = EditStore(tmp_path / "edits"), VersionStore(tmp_path / "versions")
    monkeypatch.setattr(tools, "EditService",
                        lambda call: EditService(call, store, readonly_file=tmp_path / "ro", versions=versions))
    with pytest.raises(Exception) as err:
        asyncio.run(tools.build_server(Bridge()).call_tool("lr_compare", {"include_current": False}))
    return str(err.value)


def test_compare_error_points_to_app_in_app_mode(monkeypatch, tmp_path):
    monkeypatch.setenv(tools.APP_MODE_ENV, "1")
    text = _compare_error(monkeypatch, tmp_path)
    assert "至少需要两张图" in text and "lr_save_version" not in text and "软件界面" in text


def test_compare_error_unchanged_standalone(monkeypatch, tmp_path):
    monkeypatch.delenv(tools.APP_MODE_ENV, raising=False)
    assert "lr_save_version" in _compare_error(monkeypatch, tmp_path)
