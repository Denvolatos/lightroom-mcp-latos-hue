"""The new tools through the MCP layer, with a fake bridge: lr_export (what it accepts and what it passes on), lr_save_version,
lr_list_versions, lr_apply_version, lr_compare."""
import asyncio
import json
import urllib.parse

import pytest
from PIL import Image

from lightroom_mcp import config, previews, tools
from lightroom_mcp.edits import EditService, EditStore
from lightroom_mcp.versions import VersionStore

PHOTO = "AAAAAAAA-1111"


class FakeBridge:
    """Answers the few plug-in commands these tools use; remembers every call."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.calls = []
        self.values = {"Exposure2012": 0.0, "Contrast2012": 0.0}
        self.color = (60, 120, 200)

    def call(self, command, params=None, timeout=30):
        params = params or {}
        self.calls.append((command, params))
        if command in ("get_develop", "list_selected"):
            photo = {"id": PHOTO, "name": "one.ARW"}
            if command == "list_selected":
                return {"active_id": PHOTO, "count": 1, "photos": [photo]}
            hsl = {c: {"hue": 0, "saturation": 0, "luminance": 0} for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")}
            return {"photo": photo, "settings": dict(self.values), "hsl": hsl}
        if command == "snapshot":
            return {"photo": {"id": PHOTO, "name": "one.ARW"}, "settings": dict(self.values), "has_local_adjustments": False}
        if command == "get_preview":
            path = self.tmp / f"p_{len(self.calls)}.jpg"
            Image.new("RGB", (80, 60), self.color).save(path)
            return {"path": str(path), "name": "one.ARW"}
        if command == "restore_settings":
            values = json.loads(urllib.parse.unquote(params["blob"]))
            self.values.update(values)
            return {"before": {}, "after": values, "verified": True, "restored": len(values)}
        if command == "export_photo":
            return {"path": "x", "file": "one_LrMCP_full.jpg", "folder": "x", "bytes": 1}
        raise AssertionError(command)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PREVIEW_DIR", tmp_path)
    monkeypatch.setattr(previews, "clean_old", lambda: 0)
    bridge = FakeBridge(tmp_path)
    store = EditStore(tmp_path / "edits")
    versions = VersionStore(tmp_path / "versions")
    monkeypatch.setattr(tools, "EditService", lambda call: EditService(call, store, readonly_file=tmp_path / "ro", versions=versions))
    return bridge, tools.build_server(bridge)


def run(srv, name, args):
    return asyncio.run(srv.call_tool(name, args))


def error_text(srv, name, args):
    with pytest.raises(Exception) as err:
        run(srv, name, args)
    return str(err.value)


def test_export_needs_a_place_the_user_named(server):
    bridge, srv = server
    assert "请先问用户导出到哪里" in error_text(srv, "lr_export", {})
    assert "请先问用户导出到哪里" in error_text(srv, "lr_export", {"folder": "D:\\out", "destination": "desktop"})
    assert not [c for c in bridge.calls if c[0] == "export_photo"]


def test_export_refuses_what_is_not_a_local_absolute_folder_or_a_sane_option(server):
    bridge, srv = server
    for folder in ("\\\\server\\share", "//server/share", "relative\\dir", "dir", "D:\\a\x07b", "D:\\" + "x" * 500):
        assert error_text(srv, "lr_export", {"folder": folder}), folder
    assert "destination" in error_text(srv, "lr_export", {"destination": "downloads"})
    for bad in ({"long_edge": 100}, {"long_edge": 99999}, {"quality": 10}, {"quality": 101}, {"metadata": "everything"}):
        assert error_text(srv, "lr_export", {"destination": "desktop", **bad}), bad
    assert not [c for c in bridge.calls if c[0] == "export_photo"]


def test_export_passes_the_users_folder_percent_encoded_and_nothing_else(server):
    bridge, srv = server
    folder = "D:\\照片 备份\\导出"
    result = run(srv, "lr_export", {"folder": folder, "long_edge": 2048, "quality": 85, "metadata": "all"})
    assert json.loads(result.content[0].text)["file"] == "one_LrMCP_full.jpg"
    sent = [p for c, p in bridge.calls if c == "export_photo"][0]
    assert urllib.parse.unquote(sent["folder"]) == folder and " " not in sent["folder"]
    assert sent["long_edge"] == "2048" and sent["quality"] == "85" and sent["metadata"] == "all" and "destination" not in sent
    run(srv, "lr_export", {"destination": "pictures"})
    sent = [p for c, p in bridge.calls if c == "export_photo"][-1]
    assert sent["destination"] == "pictures" and "folder" not in sent


def test_save_list_apply_and_compare_versions(server):
    bridge, srv = server
    saved = json.loads(run(srv, "lr_save_version", {"name": "first", "note": "calm"}).content[0].text)
    assert saved["version"] == "first" and saved["has_preview_picture"] is True
    bridge.values["Exposure2012"] = 0.9
    bridge.color = (200, 120, 60)
    run(srv, "lr_save_version", {"name": "second"})
    listing = json.loads(run(srv, "lr_list_versions", {}).content[0].text)
    assert [v["name"] for v in listing["versions"]] == ["first", "second"]

    compared = run(srv, "lr_compare", {})
    kinds = [part.type for part in compared.content]
    assert kinds == ["text", "image"]
    info = json.loads(compared.content[0].text)
    assert [e["label"] for e in info["legend"]] == ["A", "B", "C"]            # current, first, second
    assert "difference_from_A" in info["legend"][1] and "difference_from_A" not in info["legend"][0]

    applied = run(srv, "lr_apply_version", {"name": "first"})
    assert json.loads(applied.content[0].text)["settings_changed"] == 1 and bridge.values["Exposure2012"] == 0.0


def test_compare_needs_at_least_one_version(server):
    _, srv = server
    assert "至少需要两张图" in error_text(srv, "lr_compare", {})
