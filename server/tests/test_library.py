"""LibraryService (v0.15): list folder photos, thumbnails, select photos. For the desktop app only; not MCP tools."""
import asyncio
import base64
import urllib.parse

import pytest

from lightroom_mcp.bridge import BridgeError, BridgeTimeout
from lightroom_mcp.library import LibraryError, LibraryService

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class Plugin:
    def __init__(self):
        self.calls = []
        self.reply = {}
        self.raises = None

    def __call__(self, command, params=None, timeout=30.0):
        self.calls.append((command, params, timeout))
        if self.raises:
            raise self.raises
        return self.reply


@pytest.fixture
def env(tmp_path):
    folder = tmp_path / "照片 a"
    folder.mkdir()
    plugin = Plugin()
    return plugin, LibraryService(plugin), str(folder)


# ---- list_folder_photos ----
def test_list_encodes_the_path_and_passes_the_reply_through(env):
    plugin, service, folder = env
    plugin.reply = {"in_catalog": True, "total": 1, "photos": [{"id": "A-1"}]}
    assert service.list_folder_photos(folder, recursive=False, offset=5, limit=10) == plugin.reply
    command, params, _ = plugin.calls[0]
    assert command == "list_folder_photos"
    assert urllib.parse.unquote(params["path"]) == folder and " " not in params["path"]
    assert (params["recursive"], params["offset"], params["limit"]) == ("0", "5", "10")


def test_list_defaults(env):
    plugin, service, folder = env
    service.list_folder_photos(folder)
    assert plugin.calls[0][1]["recursive"] == "1" and plugin.calls[0][1]["limit"] == "200" and plugin.calls[0][1]["offset"] == "0"


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": "5"}, {"offset": -1}, {"offset": 1.5},
                                    {"recursive": 1}, {"recursive": "yes"}])
def test_list_refuses_bad_numbers(env, kwargs):
    plugin, service, folder = env
    with pytest.raises(LibraryError):
        service.list_folder_photos(folder, **kwargs)
    assert plugin.calls == []


@pytest.mark.parametrize("path", ["\\\\server\\share\\x", "//server/share/x", "relative\\x", "/etc", "D:x", "", "  ", None, 5,
                                  "D:\\a\x07b", "D:\\" + "x" * 500])
def test_list_refuses_bad_folders(env, path):
    plugin, service, _ = env
    with pytest.raises(LibraryError):
        service.list_folder_photos(path)
    assert plugin.calls == []


def test_list_refuses_dotdot_and_missing_folders_and_files(env, tmp_path):
    plugin, service, folder = env
    with pytest.raises(LibraryError, match=r"\.\."):
        service.list_folder_photos(folder + "\\..\\x")
    with pytest.raises(LibraryError, match="不存在"):
        service.list_folder_photos(str(tmp_path / "nothing"))
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(LibraryError, match="不存在"):
        service.list_folder_photos(str(tmp_path / "f.txt"))
    assert plugin.calls == []


def test_list_timeout_is_an_error_for_the_user(env):
    plugin, service, folder = env
    plugin.raises = BridgeTimeout("slow")
    with pytest.raises(LibraryError, match="没有在时限内回复"):
        service.list_folder_photos(folder)


def test_plugin_refusals_are_not_swallowed(env):
    plugin, service, folder = env
    plugin.raises = BridgeError("这个位置不允许浏览")
    with pytest.raises(BridgeError):
        service.list_folder_photos(folder)


def test_read_only_switch_is_not_involved(env, tmp_path):
    """the service takes no read-only switch at all: listing, thumbnails and selecting change no photo"""
    plugin, service, folder = env
    (tmp_path / "readonly").write_text("")
    plugin.reply = {"thumbnails": []}
    service.list_folder_photos(folder)
    service.get_thumbnails(["A-1"])
    service.select_photos(["A-1"])
    assert [c[0] for c in plugin.calls] == ["list_folder_photos", "get_thumbnails", "select_photos"]


# ---- get_thumbnails ----
def test_thumbnails_decode_and_check_jpeg(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": [
        {"id": "A-1", "ok": True, "jpeg_base64": b64(JPEG), "width": 10, "height": 7, "bytes": len(JPEG)},
        {"id": "B-2", "ok": False, "error": "timeout"},
        {"id": "C-3", "ok": False, "error": "not_found"},
    ]}
    data = service.get_thumbnails(["A-1", "B-2", "C-3"], 128)
    assert data["size"] == 128
    first = data["thumbnails"][0]
    assert first["ok"] and first["jpeg"] == JPEG and first["bytes"] == len(JPEG) and (first["width"], first["height"]) == (10, 7)
    assert data["thumbnails"][1] == {"id": "B-2", "ok": False, "error": "timeout"}
    command, params, timeout = plugin.calls[0]
    assert command == "get_thumbnails" and params["size"] == "128" and urllib.parse.unquote(params["ids"]) == "A-1,B-2,C-3"
    assert timeout >= 30 + 8 * 3     # long enough for the plug-in's 8 s per photo


def test_thumbnails_reject_non_jpeg_bad_base64_and_oversize(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": [
        {"id": "A-1", "ok": True, "jpeg_base64": b64(b"\x89PNG....")},
        {"id": "B-2", "ok": True, "jpeg_base64": "###not base64###"},
        {"id": "C-3", "ok": True, "jpeg_base64": b64(b"\xff\xd8" + b"x" * (150 * 1024))},
        {"id": "D-4", "ok": True, "jpeg_base64": ""},
    ]}
    errors = [t["error"] for t in service.get_thumbnails("A-1,B-2,C-3,D-4")["thumbnails"]]
    assert errors == ["bad_jpeg", "bad_jpeg", "too_large", "bad_jpeg"]


def test_thumbnails_exactly_150kb_is_accepted(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": [{"id": "A-1", "ok": True, "jpeg_base64": b64(b"\xff\xd8" + b"x" * (150 * 1024 - 2))}]}
    assert service.get_thumbnails(["A-1"])["thumbnails"][0]["ok"]


def test_thumbnails_ignore_ids_that_were_not_asked_for_and_bad_shapes(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": [{"id": "OTHER-9", "ok": True, "jpeg_base64": b64(JPEG)}, "junk",
                                   {"id": "A-1", "ok": True, "jpeg_base64": b64(JPEG)}]}
    assert [t["id"] for t in service.get_thumbnails(["A-1"])["thumbnails"]] == ["A-1"]
    plugin.reply = {"thumbnails": "nope"}
    with pytest.raises(BridgeError):
        service.get_thumbnails(["A-1"])


@pytest.mark.parametrize("ids, size", [([], 256), ("", 256), (["a b"], 256), (["a;b"], 256), (["../x"], 256), ([5], 256),
                                       (["x" * 65], 256), ([f"ID-{i}" for i in range(25)], 256),
                                       (["A-1"], 63), (["A-1"], 513), (["A-1"], True), (["A-1"], "256"), (["A-1"], 256.0),
                                       (None, 256)])
def test_thumbnails_refuse_bad_parameters(env, ids, size):
    plugin, service, _ = env
    with pytest.raises(LibraryError):
        service.get_thumbnails(ids, size)
    assert plugin.calls == []


def test_thumbnails_size_limits_and_24_ids_are_accepted(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": []}
    service.get_thumbnails([f"ID-{i}" for i in range(24)], 64)
    service.get_thumbnails(["A-1"], 512)
    assert len(plugin.calls) == 2


def test_thumbnails_duplicates_are_asked_once(env):
    plugin, service, _ = env
    plugin.reply = {"thumbnails": []}
    service.get_thumbnails(["A-1", "A-1"])
    assert urllib.parse.unquote(plugin.calls[0][1]["ids"]) == "A-1"


def test_thumbnails_timeout(env):
    plugin, service, _ = env
    plugin.raises = BridgeTimeout("slow")
    with pytest.raises(LibraryError, match="没有在时限内回复"):
        service.get_thumbnails(["A-1"])


# ---- select_photos ----
def test_select_passes_encoded_parameters_and_reports_status(env):
    plugin, service, folder = env
    plugin.reply = {"selected": ["A-1", "B-2"], "missing": [], "not_selected": [], "all_selected": True, "folder_shown": True,
                    "reason": None}
    data = service.select_photos(["A-1", "B-2"], active="B-2", show_folder=folder)
    assert data["status"] == "selected" and data["selected"] == ["A-1", "B-2"]
    command, params, _ = plugin.calls[0]
    assert command == "select_photos" and urllib.parse.unquote(params["ids"]) == "A-1,B-2" and params["active"] == "B-2"
    assert urllib.parse.unquote(params["show_folder"]) == folder
    assert all(" " not in v for v in params.values())


def test_select_optional_parameters_are_left_out(env):
    plugin, service, _ = env
    plugin.reply = {"selected": ["A-1"], "all_selected": True}
    service.select_photos("A-1")
    assert set(plugin.calls[0][1]) == {"ids"}


def test_select_partial_is_not_reported_as_success(env):
    plugin, service, _ = env
    plugin.reply = {"selected": ["A-1"], "missing": ["B-2"], "not_selected": ["C-3"], "all_selected": False, "reason": "不在当前视图"}
    data = service.select_photos(["A-1", "B-2", "C-3"])
    assert data["status"] == "partial" and data["not_selected"] == ["C-3"] and data["missing"] == ["B-2"] and data["reason"]


def test_select_timeout_means_uncertain_not_failed(env):
    plugin, service, _ = env
    plugin.raises = BridgeTimeout("slow")
    data = service.select_photos(["A-1"])
    assert data["status"] == "uncertain" and data["all_selected"] is False and "不确定" in data["message"]


def test_select_plugin_refusal_is_raised(env):
    plugin, service, _ = env
    plugin.raises = BridgeError("在当前目录里找不到这些照片")
    with pytest.raises(BridgeError):
        service.select_photos(["A-1"])


@pytest.mark.parametrize("kwargs", [
    {"ids": []}, {"ids": ["a b"]}, {"ids": [f"ID-{i}" for i in range(51)]},
    {"ids": ["A-1"], "active": "B-2"}, {"ids": ["A-1"], "active": "bad id"}, {"ids": ["A-1"], "active": 5},
    {"ids": ["A-1"], "show_folder": "\\\\server\\share"}, {"ids": ["A-1"], "show_folder": "relative"},
    {"ids": ["A-1"], "show_folder": "D:\\a\\..\\b"}, {"ids": ["A-1"], "show_folder": "Z:\\no\\such\\folder"},
])
def test_select_refuses_bad_parameters(env, kwargs):
    plugin, service, _ = env
    with pytest.raises(LibraryError):
        service.select_photos(**kwargs)
    assert plugin.calls == []


def test_select_accepts_50_ids(env):
    plugin, service, _ = env
    plugin.reply = {"selected": [], "all_selected": False}
    service.select_photos([f"ID-{i}" for i in range(50)])
    assert len(plugin.calls) == 1


# ---- not an MCP tool ----
def test_no_mcp_tool_for_library_browsing():
    from lightroom_mcp.tools import build_server

    tools = asyncio.run(build_server(None, "x").list_tools())
    assert len(tools) == 22
    bad = [t.name for t in tools if any(w in t.name for w in ("list_folder", "thumbnail", "select_photos", "library"))]
    assert not bad, bad
    assert not [t.name for t in tools if "folder" in t.name]
