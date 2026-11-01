"""The MCP server: read-only tools to look at photos, and (v1.1) a small, guarded set of tools to change sliders."""
from __future__ import annotations

import json
import re
from functools import wraps
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, config, previews
from .bridge import Bridge
from .edits import EditService, describe_limits

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
# Changes are reversible (the old values are saved) and writing the same values twice changes nothing more.
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_PHOTO_REF = re.compile(r"^(selected|[A-Za-z0-9\-]{8,64})$")

INSTRUCTIONS = (
    "这是 Lightroom Classic 的助手：可以查看当前选中的照片、读取调整参数、生成预览图并给出直方图数字，"
    "也可以小步修改一部分滑块（lr_set_develop）并随时还原（lr_restore / lr_restore_original）。"
    "先用 lr_status 确认 Lightroom 已连上。修改前先用 lr_get_preview 看现状；每次只做一小步，改完再用 lr_get_preview "
    "看效果；不满意就还原。一次只改一张照片，只改用户要求的那张。向用户用大白话说明改了什么、为什么、预期会看到什么变化。"
    "用户可能是调色新手。如果开启了只读模式（~/LrMcp/readonly），所有修改都会被拒绝。"
)

SET_DESCRIPTION = (
    "修改一张照片的调整滑块（不能超出下面的范围；白平衡、色调曲线、蒙版、裁剪、预设暂不支持）。\n"
    "changes：{参数名: 目标数值}，例如 {\"Exposure2012\": 0.3, \"Highlights2012\": -20}。给的是**目标值**，不是增量。\n"
    "每个参数的范围，以及一次调用最多能改多少（超过会被拒绝，请分几次改，每次改完用 lr_get_preview 看效果）：\n"
    f"{describe_limits()}\n"
    "reason：一句话说明为什么这样改（会记在修改记录里）。photo：\"selected\"（默认）或 lr_list_selected 返回的 id。"
    "preview：为 true 时改完顺便返回一张预览图。\n"
    "每次修改前，旧值都已存到磁盘；返回的 edit_id 可交给 lr_restore 还原。"
)


def _text(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _guard(fn):
    """mcp 2.x only shows the model the text of a ToolError; any other exception becomes a generic message.
    Our own errors (bad argument, plug-in not connected, plug-in error, timeout) are written in Chinese for the
    user, so turn them into ToolError."""

    @wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, RuntimeError) as e:  # BridgeError / PluginNotConnected are RuntimeErrors
            raise ToolError(str(e)) from e

    return inner


def _check_photo(photo: str) -> str:
    if not _PHOTO_REF.match(photo):
        raise ValueError('photo 只能是 "selected"（当前选中的照片）或 lr_list_selected 返回的 id')
    return photo


def build_server(bridge: Bridge | None, busy_message: str | None = None) -> MCPServer:
    """Create the MCP server. ``bridge`` is None when the port was busy; tools then explain why."""
    mcp = MCPServer("lightroom_mcp", instructions=INSTRUCTIONS, version=__version__)

    def call(command: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        if bridge is None:
            raise RuntimeError(busy_message or "桥接服务没有启动")
        return bridge.call(command, params, timeout)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_status() -> str:
        """检查 Lightroom 是否连上，返回 Lightroom 版本、当前目录、插件版本和选中照片数量。"""
        info: dict = {"server_version": __version__}
        if bridge is None:
            info.update(connected=False, message=busy_message)
        elif not bridge.connected and not bridge.wait_connected(bridge.connect_wait):
            info.update(
                connected=False,
                message="Lightroom 插件没有连上：请确认 Lightroom 已打开并安装了 LrMCP 插件，运行 lr_doctor 查看原因。",
            )
        else:
            info["connected"] = True
            info.update(call("status", timeout=15))
            info["bridge_port"] = bridge.port
            info["other_ai_sessions_with_a_server"] = len(bridge.other_servers())
        return _text(info)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_list_selected(limit: int = 20) -> str:
        """列出 Lightroom 当前选中的照片（最多 20 张）：id、文件名、格式、评分、旗标、尺寸和拍摄参数。"""
        limit = max(1, min(int(limit), 20))
        return _text(call("list_selected", {"limit": limit}, timeout=30))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_get_develop(photo: str = "selected") -> str:
        """读取一张照片当前的调整参数（曝光、对比度、高光、阴影、白平衡、HSL 等）。
        photo：\"selected\" 表示当前选中的照片，或 lr_list_selected 返回的 id。
        注意：RAW 照片在没编辑过时读不到 Temperature/Tint，只显示 WhiteBalance。"""
        return _text(call("get_develop", {"photo": _check_photo(photo)}, timeout=30))

    def preview_of(photo: str, long_edge: int) -> tuple[dict, Image]:
        edge = max(config.PREVIEW_MIN_EDGE, min(int(long_edge), config.PREVIEW_MAX_EDGE))
        data = call("get_preview", {"photo": _check_photo(photo), "long_edge": edge}, timeout=60)
        path = Path(str(data.get("path", ""))).resolve()
        folder = config.PREVIEW_DIR.resolve()
        if folder not in path.parents or not path.is_file():
            raise RuntimeError("插件返回的预览文件不在预期目录，已拒绝读取。")
        stats = previews.analyze(path)
        picture = Image(data=path.read_bytes(), format="jpeg")
        previews.clean_old()
        return {"photo": data.get("name"), "long_edge_requested": edge, "stats": stats}, picture

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_get_preview(photo: str = "selected", long_edge: int = config.PREVIEW_DEFAULT_EDGE) -> list:
        """生成一张照片当前效果的预览图（含已做的调整），并附直方图数字（亮度、过曝/欠曝比例、色调偏向）。
        photo：\"selected\" 或 lr_list_selected 返回的 id；long_edge：长边像素，256 到 2048，默认 1024。"""
        info, picture = preview_of(photo, long_edge)
        return [_text(info), picture]

    edits = EditService(call)

    @mcp.tool(annotations=WRITES, description=SET_DESCRIPTION)
    @_guard
    def lr_set_develop(changes: dict[str, float], reason: str = "", photo: str = "selected", preview: bool = False) -> list:
        result = edits.set_develop(changes, reason, _check_photo(photo))
        out: list = [_text(result)]
        if preview:
            info, picture = preview_of(result["photo_id"], config.PREVIEW_DEFAULT_EDGE)
            out[0] = _text({**result, "preview": info})
            out.append(picture)
        return out

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_restore(edit_id: str) -> str:
        """还原一次修改：把那次修改涉及的滑块写回修改前的值。edit_id 来自 lr_set_develop 的返回或 lr_list_edits。
        只还原那次修改碰过的滑块；如果之后又改过同一个滑块，会被写回那次修改之前的值。"""
        return _text(edits.restore(edit_id))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_restore_original(photo: str = "selected", dry_run: bool = False) -> str:
        """让一张照片回到 LrMCP 第一次改它之前的样子：把 LrMCP 改过的所有滑块写回最初的值。
        dry_run 为 true 时只显示会写回什么，不改任何东西。
        注意：如果你在 Lightroom 里手动改过同一个滑块，也会被覆盖。"""
        return _text(edits.restore_original(_check_photo(photo), bool(dry_run)))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_list_edits(photo: str = "all", limit: int = 20) -> str:
        """列出 LrMCP 做过的修改记录（新的在前）：编号、时间、照片、改了哪些滑块、是否已还原。
        photo：\"all\"（默认）、\"selected\" 或照片 id。"""
        return _text(edits.list_edits("all" if photo == "all" else _check_photo(photo), limit))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_doctor() -> str:
        """自检：逐项检查 Lightroom、插件、口令文件、依赖和客户端登记，并用中文说明哪里有问题、怎么处理。"""
        from . import doctor

        return doctor.format_report(doctor.run_checks(bridge, busy_message))

    return mcp
