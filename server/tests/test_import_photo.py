"""EditService.import_photo (v0.15): for the desktop app only. It is not an MCP tool; the AI cannot call it."""
import asyncio
import urllib.parse

import pytest

from lightroom_mcp.bridge import BridgeError, BridgeTimeout
from lightroom_mcp.edits import EditError, EditService, EditStore, ReadOnlyError
from lightroom_mcp.versions import VersionStore

PATH = "D:\\u7167\u7247\a b.ARW"


class Plugin:
    def __init__(self):
        self.calls = []
        self.reply = {"imported": True, "already": False, "id": "NEW-1", "name": "a b.ARW", "photo": {"id": "NEW-1"}}
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


def test_import_calls_the_plugin_with_the_percent_encoded_path(env):
    plugin, service, _ = env
    result = service.import_photo(PATH)
    assert result["status"] == "imported" and result["already"] is False and result["photo_id"] == "NEW-1"
    command, params, _timeout = plugin.calls[0]
    assert command == "import_photo" and set(params) == {"path"}
    assert urllib.parse.unquote(params["path"]) == PATH and "\\" not in params["path"]


def test_import_already_in_catalog(env):
    plugin, service, _ = env
    plugin.reply = {"imported": False, "already": True, "id": "OLD-1", "name": "a b.ARW"}
    result = service.import_photo(PATH)
    assert result["status"] == "already" and result["already"] is True and result["photo_id"] == "OLD-1"
    assert "本来就在目录里" in result["message"]


def test_read_only_mode_refuses_before_the_plugin_is_asked(env):
    plugin, service, tmp = env
    (tmp / "readonly").write_text("")
    with pytest.raises(ReadOnlyError, match="只读模式"):
        service.import_photo(PATH)
    assert plugin.calls == []


def test_read_only_environment_variable_also_refuses(env, monkeypatch):
    plugin, service, _ = env
    monkeypatch.setenv("LRMCP_READONLY", "1")
    with pytest.raises(ReadOnlyError):
        service.import_photo(PATH)
    assert plugin.calls == []


def test_timeout_means_the_result_is_uncertain(env):
    plugin, service, _ = env
    plugin.raises = BridgeTimeout("reply timed out")
    result = service.import_photo(PATH)
    assert result["status"] == "uncertain" and "在 Lightroom 里确认" in result["message"]


def test_plugin_refusal_is_passed_on(env):
    plugin, service, _ = env
    plugin.raises = BridgeError("这个文件不存在")
    with pytest.raises(BridgeError, match="不存在"):
        service.import_photo(PATH)


@pytest.mark.parametrize("bad", [None, "", "   ", 5])
def test_empty_path_is_refused_without_asking_the_plugin(env, bad):
    plugin, service, _ = env
    with pytest.raises(EditError):
        service.import_photo(bad)
    assert plugin.calls == []


def test_no_mcp_tool_for_import_the_ai_cannot_call_it():
    from lightroom_mcp.tools import build_server

    names = [t.name for t in asyncio.run(build_server(None, "x").list_tools())]
    assert len(names) == 22
    assert not [n for n in names if "import" in n.lower()]
