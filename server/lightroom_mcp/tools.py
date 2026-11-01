"""The MCP server: five read-only tools. Nothing here can change a photo."""
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

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_PHOTO_REF = re.compile(r"^(selected|[A-Za-z0-9\-]{8,64})$")

INSTRUCTIONS = (
    "这是 Lightroom Classic 的只读助手：可以查看当前选中的照片、读取调整参数、生成预览图并给出直方图数字。"
    "本版本不能修改任何照片。先用 lr_status 确认 Lightroom 已连上；需要看图时用 lr_get_preview。"
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

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_get_preview(photo: str = "selected", long_edge: int = config.PREVIEW_DEFAULT_EDGE) -> list:
        """生成一张照片当前效果的预览图（含已做的调整），并附直方图数字（亮度、过曝/欠曝比例、色调偏向）。
        photo：\"selected\" 或 lr_list_selected 返回的 id；long_edge：长边像素，256 到 2048，默认 1024。"""
        edge = max(config.PREVIEW_MIN_EDGE, min(int(long_edge), config.PREVIEW_MAX_EDGE))
        data = call("get_preview", {"photo": _check_photo(photo), "long_edge": edge}, timeout=60)
        path = Path(str(data.get("path", ""))).resolve()
        folder = config.PREVIEW_DIR.resolve()
        if folder not in path.parents or not path.is_file():
            raise RuntimeError("插件返回的预览文件不在预期目录，已拒绝读取。")
        stats = previews.analyze(path)
        picture = Image(data=path.read_bytes(), format="jpeg")
        previews.clean_old()
        info = {"photo": data.get("name"), "long_edge_requested": edge, "stats": stats}
        return [_text(info), picture]

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_doctor() -> str:
        """自检：逐项检查 Lightroom、插件、口令文件、依赖和客户端登记，并用中文说明哪里有问题、怎么处理。"""
        from . import doctor

        return doctor.format_report(doctor.run_checks(bridge, busy_message))

    return mcp
