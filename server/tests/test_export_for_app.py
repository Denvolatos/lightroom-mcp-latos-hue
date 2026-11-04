# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""EditService.export_photo_for_app (v0.15): TIFF/JPEG export for the desktop app only. Not an MCP tool; lr_export is unchanged."""
import asyncio
import urllib.parse

import pytest

from lightroom_mcp.bridge import BridgeError, BridgeTimeout
from lightroom_mcp.edits import EditError, EditService, EditStore
from lightroom_mcp.versions import VersionStore

FOLDER = "D:\\\u7167\u7247\\\u5bfc\u51fa out"


class Plugin:
    def __init__(self):
        self.calls = []
        self.reply = {"path": FOLDER + "\\one_LrMCP_full.tif", "file": "one_LrMCP_full.tif", "format": "tiff", "extension": "tif",
                      "bit_depth": 16, "width": 6000, "height": 4000}
        self.raises = None

    def __call__(self, command, params=None, timeout=30.0):
        self.calls.append((command, params, timeout))
        if self.raises:
            raise self.raises
        return self.reply


@pytest.fixture
def env(tmp_path):
    plugin = Plugin()
    service = EditService(plugin, EditStore(tmp_path / "edits"), readonly_file=tmp_path / "readonly",
                          versions=VersionStore(tmp_path / "versions"))
    return plugin, service, tmp_path


def test_tiff_is_sent_percent_encoded_with_bit_depth_and_without_quality(env):
    plugin, service, _ = env
    result = service.export_photo_for_app(FOLDER, "tiff", long_edge=2048, quality=70, metadata="all", bit_depth=8)
    assert result["status"] == "exported" and result["file"] == "one_LrMCP_full.tif"
    command, params, timeout = plugin.calls[0]
    assert command == "export_photo" and timeout >= 120
    assert params == {"photo": "selected", "folder": urllib.parse.quote(FOLDER, safe=""), "format": "tiff", "long_edge": "2048",
                      "metadata": "all", "bit_depth": "8"}
    assert urllib.parse.unquote(params["folder"]) == FOLDER and "\\" not in params["folder"]


def test_jpeg_sends_quality_and_no_bit_depth(env):
    plugin, service, _ = env
    service.export_photo_for_app(FOLDER)
    params = plugin.calls[0][1]
    assert params["format"] == "jpeg" and params["quality"] == "90" and "bit_depth" not in params


def test_tiff_defaults_to_16_bit(env):
    plugin, service, _ = env
    service.export_photo_for_app(FOLDER, "tiff")
    assert plugin.calls[0][1]["bit_depth"] == "16"


@pytest.mark.parametrize("kwargs", [
    dict(format="png"), dict(format="TIFF"), dict(format=""), dict(format=None),
    dict(long_edge=100), dict(long_edge=20001), dict(long_edge=-1), dict(long_edge=True), dict(long_edge="1024"), dict(long_edge=1024.0),
    dict(quality=39), dict(quality=101), dict(quality=True), dict(quality="90"),
    dict(bit_depth=12), dict(bit_depth=0), dict(bit_depth=True), dict(bit_depth="16"),
    dict(metadata="none"), dict(metadata=""), dict(photo="a;b"), dict(photo=""),
])
def test_out_of_range_parameters_are_refused_before_the_plugin_is_asked(env, kwargs):
    plugin, service, _ = env
    with pytest.raises(EditError):
        service.export_photo_for_app(FOLDER, **{"format": "tiff", **kwargs})
    assert plugin.calls == []


@pytest.mark.parametrize("folder", [
    "", "   ", None, 5, "relative\\dir", "photos", "\\\\server\\share\\x", "//server/share/x", "D:\\a\x07b", "D:\\" + "x" * 500, "D:",
])
def test_folders_that_are_not_absolute_local_paths_are_refused(env, folder):
    plugin, service, _ = env
    with pytest.raises(EditError):
        service.export_photo_for_app(folder, "tiff")
    assert plugin.calls == []


def test_boundary_values_are_accepted(env):
    plugin, service, _ = env
    for edge in (0, 256, 20000):
        service.export_photo_for_app(FOLDER, "tiff", long_edge=edge)
    for q in (40, 100):
        service.export_photo_for_app(FOLDER, "jpeg", quality=q)
    for depth in (8, 16):
        service.export_photo_for_app(FOLDER, "tiff", bit_depth=depth)
    assert len(plugin.calls) == 7


def test_a_timeout_means_uncertain_not_failed(env):
    plugin, service, _ = env
    plugin.raises = BridgeTimeout("no answer")
    result = service.export_photo_for_app(FOLDER, "tiff")
    assert result["status"] == "uncertain" and "文件夹里确认" in result["message"] and result["folder"] == FOLDER


def test_plugin_refusals_are_not_swallowed(env):
    plugin, service, _ = env
    plugin.raises = BridgeError("这个位置不允许导出")
    with pytest.raises(BridgeError):
        service.export_photo_for_app(FOLDER, "tiff")


def test_read_only_mode_does_not_block_export(env):
    plugin, service, tmp = env
    (tmp / "readonly").write_text("")
    assert service.export_photo_for_app(FOLDER, "tiff")["status"] == "exported"
    assert len(plugin.calls) == 1


def test_no_new_mcp_tool_and_lr_export_is_unchanged():
    from lightroom_mcp.tools import build_server

    tools = asyncio.run(build_server(None, "x").list_tools())
    assert len(tools) == 22
    assert not [t.name for t in tools if "for_app" in t.name or "tiff" in t.name.lower() or "import" in t.name]
    export = [t for t in tools if t.name == "lr_export"][0]
    assert set(export.input_schema["properties"]) == {"photo", "folder", "destination", "long_edge", "quality", "metadata"}
    assert "TIFF" not in (export.description or "").upper()
