# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
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
from .edits import EditService, describe_limits, describe_limits_en
from .update import UpdateChecker
import urllib.parse

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
# Changes are reversible (the old values are saved) and writing the same values twice changes nothing more.
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EXPORTS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DELETES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
_PHOTO_REF = re.compile(r"^(selected|[A-Za-z0-9\-]{8,64})$")

INSTRUCTIONS = (
    "Assistant for Adobe Lightroom Classic. It can look at the photo the user selected (develop settings, preview image with histogram "
    "numbers, catalog information), make small guarded changes (sliders, curves, crop, presets, rating/flags/keywords, batch changes "
    "with a dry run first) and undo every change (lr_restore / lr_restore_original). Start with lr_status. Before changing anything look "
    "at the photo with lr_get_preview; change a little at a time and look again; undo if it does not look better. One photo at a time "
    "(batch only on request), only the photo the user asked for, and only when the user asked for a change. Explain in plain words what "
    "you changed, why and what to expect: the user may be a beginner. Reply in the user's language; the messages returned by the tools "
    "are in Chinese, translate them when needed. If read-only mode is on (~/LrMcp/readonly) every change is refused. "
    "Masks (local adjustments) cannot be changed. Save named versions (lr_save_version) before big changes and compare them (lr_compare); export (lr_export) only to the place the user named. Use lr_review_selected to compare selected photos and lr_plan_from_edit "
    "to rehearse reusing a verified edit on other photos.\n\n"
    "这是 Lightroom Classic 的助手：可以查看用户选中的照片（调整参数、带直方图数字的预览图、目录信息），小步且有保护地修改"
    "（滑块、曲线、裁剪、预设、星级/旗标/关键词、先预演的批量修改），并随时还原每一次修改（lr_restore / lr_restore_original）。"
    "先用 lr_status 确认 Lightroom 已连上。修改前先用 lr_get_preview 看现状；每次只做一小步，改完再看；不满意就还原。"
    "一次只改一张照片（批量只在用户要求时用），只改用户要求的那张，只在用户要求修改时才改。向用户用大白话说明改了什么、为什么、"
    "预期会看到什么变化，用户可能是新手。用用户的语言回复；工具返回的提示是中文。如果开启了只读模式（~/LrMcp/readonly），"
    "所有修改都会被拒绝。蒙版（局部调整）不能改。大改之前先存版本（lr_save_version），用 lr_compare 对比；导出（lr_export）只放用户说的位置。挑片用 lr_review_selected；复用单张修改先用 lr_plan_from_edit 预演。"
)

SET_DESCRIPTION = (
    "Change develop settings of ONE photo (sliders, white balance of RAW photos, colour grading, calibration, tone curves, sharpening, "
    "noise reduction, vignettes, grain, crop and straighten). Not possible: masks, presets (use lr_apply_preset).\n"
    "changes: {parameter name: TARGET value}, e.g. {\"Exposure2012\": 0.3, \"Highlights2012\": -20}. These are target values, not increments. "
    "A value outside its range is refused, and so is a bigger change than the per-call limit (change in several small steps and look "
    "at lr_get_preview after each one). Ranges and limits:\n"
    f"{describe_limits_en()}\n"
    "reason: one sentence saying why (kept in the edit history). photo: \"selected\" (default) or an id from lr_list_selected. "
    "preview: true returns before and after previews plus numeric differences. The old values are saved to disk before anything is written; "
    "the returned edit_id can be given to lr_restore.\n\n"
    "中文：修改**一张**照片的调整参数（滑块、RAW 的白平衡、颜色分级、校准、色调曲线、锐化、降噪、暗角、颗粒、裁剪与拉直）。"
    "做不到：蒙版；预设请用 lr_apply_preset。\n"
    "changes：{参数名: 目标数值}，例如 {\"Exposure2012\": 0.3, \"Highlights2012\": -20}。给的是**目标值**，不是增量。"
    "超出范围、或一次改得比单次限幅还大都会被拒绝，请分几次改，每次改完用 lr_get_preview 看效果。每个参数的范围和单次限幅：\n"
    f"{describe_limits()}\n"
    "reason：一句话说明为什么这样改（会记在修改记录里）。photo：\"selected\"（默认）或 lr_list_selected 返回的 id。"
    "preview：为 true 时返回修改前后两张预览及统计差异。每次修改前，旧值都已存到磁盘；返回的 edit_id 可交给 lr_restore 还原。"
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


def build_server(bridge: Bridge | None, busy_message: str | None = None, updates: UpdateChecker | None = None) -> MCPServer:
    """Create the MCP server. ``bridge`` is None when the port was busy; tools then explain why."""
    mcp = MCPServer("lightroom_mcp", instructions=INSTRUCTIONS, version=__version__)

    def call(command: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        if bridge is None:
            raise RuntimeError(busy_message or "桥接服务没有启动")
        return bridge.call(command, params, timeout)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_status() -> str:
        """Check that Lightroom is connected; returns the Lightroom version, the catalog, the plug-in version and whether a photo is selected.
        If the reply has "update_available", tell the user (nothing is downloaded or installed automatically).

        检查 Lightroom 是否连上，返回 Lightroom 版本、当前目录、插件版本和是否有选中照片。有 update_available 时请告诉用户（不会自动更新）。"""
        info: dict = {"server_version": __version__}
        notice = updates.notice() if updates else None
        if notice:
            info["update_available"] = notice
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
        """List the photos selected in Lightroom (at most 20): id, file name, format, rating, flag, size and shooting data.
        The ids are what the other tools take as `photo`.

        列出 Lightroom 当前选中的照片（最多 20 张）：id、文件名、格式、评分、旗标、尺寸和拍摄参数。其他工具的 photo 参数用这里的 id。"""
        limit = max(1, min(int(limit), 20))
        return _text(call("list_selected", {"limit": limit}, timeout=30))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_get_develop(photo: str = "selected") -> str:
        """Read the current develop settings of a photo (exposure, contrast, highlights, shadows, white balance, HSL, curves, crop ...).
        photo: "selected" (the selected photo) or an id from lr_list_selected.
        Note: JPEGs have no Temperature/Tint (no kelvin value); an unedited RAW may not show them either, only WhiteBalance.

        读取一张照片当前的调整参数（曝光、对比度、高光、阴影、白平衡、HSL、曲线、裁剪等）。
        photo："selected" 表示当前选中的照片，或 lr_list_selected 返回的 id。
        注意：JPEG 读不到 Temperature/Tint（没有开尔文值）；RAW 没编辑过时也可能读不到，只显示 WhiteBalance。"""
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
        """Render a preview image of the photo as it looks now (adjustments and crop included) plus histogram numbers (brightness,
        share of clipped highlights/shadows, colour cast). photo: "selected" or an id from lr_list_selected; long_edge: pixels of the
        long side, 256 to 2048, default 1024. The preview is sent to the AI service the user is using.

        生成一张照片当前效果的预览图（含已做的调整和裁剪），并附直方图数字（亮度、过曝/欠曝比例、色调偏向）。
        photo："selected" 或 lr_list_selected 返回的 id；long_edge：长边像素，256 到 2048，默认 1024。预览图会发给用户正在使用的 AI 服务。"""
        info, picture = preview_of(photo, long_edge)
        return [_text(info), picture]

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_review_selected(limit: int = 6, long_edge: int = 512) -> list:
        """Show previews and photo details for up to 10 selected photos in one reply, in Lightroom selection order.
        This is read-only: suggest picks from the images, then ask before changing ratings or flags.

        一次查看最多 10 张已选照片的预览和参数统计，用于对比挑片；本工具不会改星级或旗标。"""
        count = max(1, min(int(limit), 10))
        listing = call("list_selected", {"limit": count}, timeout=30)
        if not listing.get("photos"):
            raise ValueError("Lightroom 里没有选中的照片。")
        rows, images = [], []
        for photo_info in listing["photos"]:
            info, picture = preview_of(photo_info["id"], long_edge)
            rows.append({**photo_info, "preview": info})
            images.append(picture)
        return [_text({"selected_count": listing["count"], "shown": len(rows),
                       "photos": rows, "image_order": [p["id"] for p in rows]}), *images]

    edits = EditService(call)

    @mcp.tool(annotations=WRITES, description=SET_DESCRIPTION)
    @_guard
    def lr_set_develop(changes: dict[str, float | list], reason: str = "", photo: str = "selected", preview: bool = False) -> list:
        photo = _check_photo(photo)
        if preview:
            edits.check_writable()
            if photo == "selected":
                photo = call("list_selected", {"limit": 1}, timeout=30).get("active_id") or "selected"
            before_info, before_image = preview_of(photo, config.PREVIEW_DEFAULT_EDGE)
        result = edits.set_develop(changes, reason, photo)
        out: list = [_text(result)]
        if preview:
            try:
                info, picture = preview_of(result["photo_id"], config.PREVIEW_DEFAULT_EDGE)
            except (OSError, RuntimeError) as e:
                return [_text({**result, "before_preview": before_info, "preview_error": str(e)}), before_image]
            out[0] = _text({**result, "before_preview": before_info, "preview": info,
                            "preview_delta": previews.compare_stats(before_info["stats"], info["stats"]),
                            "image_order": ["before", "after"]})
            out.extend([before_image, picture])
        return out

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_get_metadata(photo: str = "selected") -> str:
        """Read the catalog information of a photo: rating (0 to 5), flag (pick / none / reject), colour label, title, caption, keywords.

        读取一张照片的目录信息：星级（0 到 5）、旗标（pick 留用 / none / reject 排除）、颜色标签、标题、说明文字、关键词。"""
        return _text(edits.get_metadata(_check_photo(photo)))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_set_metadata(rating: int | None = None, flag: str | None = None, color_label: str | None = None,
                        title: str | None = None, caption: str | None = None,
                        add_keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
                        reason: str = "", photo: str = "selected") -> str:
        """Change the catalog information (not the develop settings) of ONE photo; give only what should change: rating 0 to 5 (0 = no
        stars); flag: pick / none / reject; color_label: red, yellow, green, blue, purple or none; title (up to 200 characters, empty
        string clears it); caption (up to 1000 characters); add_keywords / remove_keywords: lists of names (up to 10 per call, each up
        to 60 characters, no commas; a new keyword is created at the top level of the keyword list). The old values are saved first;
        give the returned edit_id to lr_restore to undo (a keyword created by the change stays in Lightroom's keyword list, it is only
        taken off the photo). Only change this when the user clearly asked, especially reject and clearing a title or caption.

        修改**一张**照片的目录信息（不是调整参数），只给要改的项：rating 星级 0 到 5（0 是没有星）；flag：pick 留用 /
        none / reject 排除；color_label：red、yellow、green、blue、purple 或 none；title 标题（最多 200 字，空字符串清空）；
        caption 说明文字（最多 1000 字）；add_keywords / remove_keywords 关键词列表（一次最多 10 个，每个最多 60 个字符，
        不含逗号；新关键词会被创建在 Lightroom 的关键词列表顶层）。改之前旧值先存盘，返回的 edit_id 可交给 lr_restore 还原
        （新建过的关键词会留在关键词列表里，只是从这张照片上去掉）。只在用户明确要求时才改，尤其是排除（reject）和清空标题/说明文字。"""
        return _text(edits.set_metadata(rating, flag, color_label, title, caption, add_keywords, remove_keywords, reason, _check_photo(photo)))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_list_presets(query: str = "", limit: int = 30) -> str:
        """List the develop presets in Lightroom (at most 50 per call): id, name, folder, whether it has masks (those cannot be applied).
        query: search in the name or folder name (ONE word, case-insensitive); leave empty to list the first ones. The reply gives the
        total count, so narrow the search with a keyword.

        列出 Lightroom 里的开发预设（最多 50 个）：id、名称、所在文件夹、是否带蒙版（带蒙版的不能套用）。
        query：按名称或文件夹名搜索（一个词，不分大小写），不填就列出前几个；返回里有总数，可以用关键词缩小范围。"""
        return _text(edits.list_presets(query, limit))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_apply_preset(preset_id: str, reason: str = "", photo: str = "selected", preview: bool = False) -> list:
        """Apply a develop preset to ONE photo (preset_id comes from lr_list_presets). A preset can change a lot at once (curves, colour
        grading, black & white, look ...), so tell the user before applying and check with lr_get_preview afterwards. The whole state of
        the photo is saved first; lr_restore or lr_restore_original brings everything back exactly. Presets with masks / AI, and photos
        that already have masks, are refused. reason: one sentence why. preview: true returns before and after previews.

        给**一张**照片套用一个开发预设（preset_id 来自 lr_list_presets）。预设可能一次改动很多地方（曲线、颜色分级、黑白、
        镜头外观……），所以套之前要和用户说清楚，套完用 lr_get_preview 看效果。套之前整张照片的设置先存盘；
        用 lr_restore 或 lr_restore_original 可以完全还原。带蒙版/AI 的预设，以及已经有蒙版的照片，会被拒绝。
        reason：一句话说明为什么套这个预设。preview：为 true 时返回套用前后两张预览及统计差异。"""
        photo = _check_photo(photo)
        if preview:
            edits.check_writable()
            if photo == "selected":
                photo = call("list_selected", {"limit": 1}, timeout=30).get("active_id") or "selected"
            before_info, before_image = preview_of(photo, config.PREVIEW_DEFAULT_EDGE)
        result = edits.apply_preset(preset_id, reason, photo)
        out: list = [_text(result)]
        if preview:
            try:
                info, picture = preview_of(result["photo_id"], config.PREVIEW_DEFAULT_EDGE)
            except (OSError, RuntimeError) as e:
                return [_text({**result, "before_preview": before_info, "preview_error": str(e)}), before_image]
            out[0] = _text({**result, "before_preview": before_info, "preview": info,
                            "preview_delta": previews.compare_stats(before_info["stats"], info["stats"]),
                            "image_order": ["before", "after"]})
            out.extend([before_image, picture])
        return out

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_batch_set_develop(changes: dict[str, float], photos: str | list[str] = "selected", reason: str = "",
                             dry_run: bool = True, plan_id: str = "") -> str:
        """Batch change: add the same RELATIVE amount to the sliders of several photos (each photo on top of its own current value),
        at most 10 photos per call. Two steps:
        1. dry_run=true (default): only a rehearsal, nothing is changed. changes are relative amounts, e.g. {"Exposure2012": 0.3,
           "Contrast2012": 10} (the per-call limits are those of lr_set_develop; crop, straighten and curves are not supported). photos:
           "selected" (all selected photos) or a list of ids from lr_list_selected. The reply shows before -> after for every photo,
           which photos would be skipped (e.g. temperature on a JPEG) and a plan_id.
        2. Explain the result to the user in plain words; only AFTER the user agrees call again with dry_run=false and that plan_id
           (valid for 15 minutes, single use). The run stops at the first failure; what was done stays and the returned batch_id given
           to lr_restore undoes the whole batch. reason: one sentence why.

        批量修改：把同样的**相对改动量**加到多张照片的滑块上（每张加在自己当前值上），一次最多 10 张。
        两步走：
        1. dry_run=true（默认）：只预演，不改任何东西。changes 是相对改动量，例如 {"Exposure2012": 0.3, "Contrast2012": 10}
           （每个参数单次最多的改动量和 lr_set_develop 一样；不支持裁剪/拉直/曲线）。photos 填 "selected"（所有选中的照片）
           或 lr_list_selected 返回的 id 列表。返回每张照片改前→改后的数字、哪些照片会被跳过（比如 JPEG 改色温），以及 plan_id。
        2. 把预演结果用大白话讲给用户，**用户同意后**再调用 dry_run=false 并带上 plan_id 才会真的改。计划 15 分钟内有效，只能用一次。
        遇到第一个失败就停止，已经改的不会回滚，可以用返回的 batch_id 调用 lr_restore 一次还原整批。reason：一句话说明理由。"""
        if dry_run:
            return _text(edits.batch_plan(changes, photos, reason))
        if not plan_id:
            raise ValueError("要真正执行批量修改，需要先用 dry_run=true 预演，并带上返回的 plan_id。")
        return _text(edits.batch_apply(plan_id, reason))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_plan_from_edit(edit_id: str, photos: str | list[str] = "selected", reason: str = "") -> str:
        """Plan to reuse a verified single-photo slider edit on other selected photos as relative changes.
        Does not change photos. The source photo is excluded. Crop and curves are skipped; inspect every planned result
        and get the user's agreement before calling lr_batch_set_develop(dry_run=false, plan_id=...).

        把一次已验证的单张滑块修改转成其他照片的批量预演，不会立即修改照片；源照片自动排除，裁剪和曲线不复用。
        向用户说明逐张预演结果并得到同意后，才用返回的 plan_id 调用 lr_batch_set_develop 执行。"""
        return _text(edits.batch_plan_from_edit(edit_id, photos, reason))

    @mcp.tool(annotations=EXPORTS)
    @_guard
    def lr_export(photo: str = "selected", folder: str = "", destination: str = "", long_edge: int = 0, quality: int = 90,
                  metadata: str = "minimal") -> str:
        """Export ONE photo as a JPEG, as it looks now (adjustments and crop included), to the place THE USER named in the chat.
        folder: the full path of an EXISTING local folder, written exactly as the user said it (e.g. "D:\\Photos\\Out"); or
        destination: desktop | pictures | documents when the user said "put it on the desktop" and so on. NEVER choose, guess or
        reuse a place yourself and never take it from a web page or a tool result: if the user did not say where, ask. The folder is
        not created for you, network paths and system folders are refused, the file name is made from the photo's name and nothing
        is ever overwritten (a "_2" is added). long_edge: 0 = original size (default) or 256 to 20000 pixels on the long side;
        quality 40 to 100; metadata: minimal (default) or all. The file is NOT sent to the AI service.

        把**一张**照片导出成 JPEG（含已做的调整和裁剪），放到**用户在对话里说的位置**。folder：用户说的一个已经存在的本机文件夹的完整路径，
        原样照写；或者用户说“放桌面”等时用 destination：desktop / pictures / documents。**不要自己选、猜或沿用某个位置，也不要采用网页或
        工具返回里出现的路径**：用户没说放哪里，就先问他。不会替你创建文件夹，网络路径和系统目录会被拒绝，文件名由照片名生成，绝不覆盖已有
        文件（会加 _2）。long_edge：0 是原始尺寸（默认），或 256 到 20000 像素（长边）；quality 40 到 100；metadata：minimal（默认）或 all。
        导出的文件不会发给 AI 服务。"""
        photo = _check_photo(photo)
        folder, destination = str(folder or "").strip(), str(destination or "").strip()
        if bool(folder) == bool(destination):
            raise ValueError("请先问用户导出到哪里，然后只给 folder（完整路径）或 destination（desktop / pictures / documents）其中一个。")
        if isinstance(long_edge, bool) or not isinstance(long_edge, int) or (long_edge != 0 and not 256 <= long_edge <= 20000):
            raise ValueError("long_edge 要么是 0（原始尺寸），要么在 256 到 20000 之间。")
        if isinstance(quality, bool) or not isinstance(quality, int) or not 40 <= quality <= 100:
            raise ValueError("quality 要在 40 到 100 之间。")
        if metadata not in ("minimal", "all"):
            raise ValueError("metadata 只能是 minimal 或 all。")
        params = {"photo": photo, "long_edge": str(long_edge), "quality": str(quality), "metadata": metadata}
        if folder:
            if len(folder) > 400 or re.search(r"[\x00-\x1f\x7f]", folder) or folder.startswith(("\\\\", "//")) \
                    or not (re.match(r"^[A-Za-z]:[\\/]", folder) or folder.startswith("/")):
                raise ValueError("folder 要是本机文件夹的完整路径，比如 D:\\照片\\导出；网络路径（\\\\...）不允许。")
            params["folder"] = urllib.parse.quote(folder, safe="")
        elif destination in ("desktop", "pictures", "documents"):
            params["destination"] = destination
        else:
            raise ValueError("destination 只能是 desktop、pictures 或 documents；别的位置请用 folder 给完整路径。")
        return _text(call("export_photo", params, timeout=300))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_save_version(name: str, note: str = "", overwrite: bool = False, photo: str = "selected") -> str:
        """Save how ONE photo looks now (all its sliders, curves, crop and white balance label) as a named version, kept in files on the
        user's computer, with a small preview picture. Use it before a big change or when the user likes a state ("save this as v2").
        name: up to 40 characters; note: up to 200; overwrite=true replaces a version with the same name. Up to 50 versions per photo.
        Masks are not part of a version. Go back with lr_apply_version, compare with lr_compare.

        把**一张**照片现在的样子（所有滑块、曲线、裁剪和白平衡标签）存成一个有名字的版本，保存在用户电脑上的文件里，并附一张小预览图。
        大改之前，或者用户喜欢某个状态时用（“把这个存成 v2”）。name：最多 40 个字；note：最多 200 个字；overwrite=true 会覆盖同名版本。
        一张照片最多 50 个版本。蒙版不在版本里。用 lr_apply_version 回到某个版本，用 lr_compare 对比。"""
        photo = _check_photo(photo)
        photo_id, _ = edits.photo_id_of(photo)
        try:
            _, picture = preview_of(photo_id, 512)
            thumbnail = picture.data
        except (OSError, RuntimeError, ValueError):
            thumbnail = None   # a version without its picture is still a version
        return _text(edits.save_version(name, note, photo_id, thumbnail, overwrite))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_list_versions(photo: str = "selected") -> str:
        """List the named versions saved for ONE photo: name, note, time, and whether it has a preview picture.

        列出**一张**照片已保存的命名版本：名字、备注、时间、有没有预览图。"""
        return _text(edits.list_versions(_check_photo(photo)))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_apply_version(name: str, reason: str = "", photo: str = "selected", preview: bool = False) -> list:
        """Put ONE photo back to a saved version (lr_list_versions shows the names). It is written as ONE change (the limits per call
        do not apply to going back to a saved state) and lr_restore can undo it, so you can switch between versions freely. Only
        what the version stores is written; masks are untouched. preview=true also returns a preview picture.

        让**一张**照片回到某个已保存的版本（名字见 lr_list_versions）。作为**一次**修改写入（回到已存的状态不受单次限幅约束），
        可以用 lr_restore 撤销，所以能在版本之间自由切换。只写版本里存的内容，不碰蒙版。preview=true 时顺便返回一张预览图。"""
        photo = _check_photo(photo)
        result = edits.apply_version(name, reason, photo)
        out: list = [_text(result)]
        if preview and result.get("photo_id"):
            info, picture = preview_of(result["photo_id"], config.PREVIEW_DEFAULT_EDGE)
            out[0] = _text({**result, "preview": info})
            out.append(picture)
        return out

    @mcp.tool(annotations=DELETES)
    @_guard
    def lr_delete_version(name: str, photo: str = "selected") -> str:
        """Delete ONE saved version record (and its small preview picture) of ONE photo. The photo and its other versions are not touched.
        Only when the user asked for it.

        删除**一张**照片的**一个**已保存版本（记录和它的小预览图）。照片本身和其他版本不受影响。只在用户要求时用。"""
        return _text(edits.delete_version(name, _check_photo(photo)))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_compare(versions: list[str] | None = None, photo: str = "selected", include_current: bool = True) -> list:
        """Put the photo's current look and its saved versions side by side in ONE picture (letters A, B, C ... in the corners) and
        return numbers for each plus the difference from the first one. versions: names to include (default: all saved versions, at
        most 5 pictures in total). A saved version is shown as it looked when it was saved.

        把照片现在的样子和它已保存的版本并排拼成**一张**图（角上标 A、B、C……），并给每个的数字和相对第一个的差异。versions：要放进来的
        版本名（默认全部，图一共最多 5 张）。已保存的版本显示的是它保存时的样子。"""
        photo = _check_photo(photo)
        photo_id, photo_name = edits.photo_id_of(photo)
        wanted = [v for v in (versions or []) if isinstance(v, str)] or [r["name"] for r in edits.versions.list(photo_id)]
        pictures: list[bytes] = []
        legend: list[dict] = []
        if include_current:
            info, picture = preview_of(photo_id, 512)
            pictures.append(picture.data)
            legend.append({"what": "现在的样子 / current", "stats": info["stats"]})
        skipped: list[str] = []
        for name in wanted:
            if len(pictures) >= 5:
                skipped.append(name)
                continue
            record = edits.versions.get(photo_id, name)
            path = edits.versions.thumbnail_path(photo_id, name)
            if path is None:
                skipped.append(name + "（没有预览图）")
                continue
            pictures.append(path.read_bytes())
            legend.append({"what": "版本：" + record["name"], "note": record.get("note", ""), "saved": record.get("created"),
                           "stats": previews.analyze(path)})
        if len(pictures) < 2:
            raise ValueError("要对比至少需要两张图：现在的样子加至少一个有预览图的版本。先用 lr_save_version 存一个版本。")
        labels = [chr(ord("A") + i) for i in range(len(pictures))]
        for label, entry in zip(labels, legend):
            entry["label"] = label
            if label != "A":
                entry["difference_from_A"] = previews.compare_stats(legend[0]["stats"], entry["stats"])
        return [_text({"photo": photo_name, "legend": legend, "not_shown": skipped}),
                Image(data=previews.compose_side_by_side(pictures, labels), format="jpeg")]

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_restore(edit_id: str, force: bool = False) -> str:
        """Undo one change: writes back the values from before that change. edit_id comes from the reply of the tool that made the change
        or from lr_list_edits; a batch_id undoes the whole batch. It works for develop changes, presets and catalog information. It only
        touches what that change touched. If a setting changed later, restore refuses to overwrite it by default;
        force=true allows overwriting after the user reviews the conflict.

        还原一次修改：把那次修改涉及的内容写回修改前的值。edit_id 来自做出修改的工具的返回或 lr_list_edits；批量修改的 batch_id 会一次还原整批。
        调整参数、预设、目录信息都适用。只还原那次修改碰过的内容；如果之后又改过同一项，默认拒绝覆盖。
        用户明确确认仍要覆盖时才用 force=true。"""
        return _text(edits.restore(edit_id, bool(force)))

    @mcp.tool(annotations=WRITES)
    @_guard
    def lr_restore_original(photo: str = "selected", dry_run: bool = False, force: bool = False) -> str:
        """Put a photo back to how it was before LrMCP first changed it: writes the original values of every develop setting LrMCP
        changed (presets included). Catalog information (rating, flag, keywords ...) is NOT touched, use lr_restore for that.
        dry_run=true shows what would be written and detected conflicts. Later changes are protected by default;
        force=true overwrites them only after the user explicitly agrees.

        让一张照片回到 LrMCP 第一次改它之前的样子：把 LrMCP 改过的所有调整参数（含预设）写回最初的值。目录信息（星级、旗标、关键词等）不受影响，
        那些请用 lr_restore。dry_run 为 true 时显示计划和检测到的冲突，不改任何东西。后续改动默认受保护；
        用户明确确认仍要覆盖时才用 force=true。"""
        return _text(edits.restore_original(_check_photo(photo), bool(dry_run), bool(force)))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_list_edits(photo: str = "all", limit: int = 20) -> str:
        """List the changes LrMCP made (newest first): id, time, photo, what was changed, whether it was restored.
        photo: "all" (default), "selected" or a photo id.

        列出 LrMCP 做过的修改记录（新的在前）：编号、时间、照片、改了什么、是否已还原。photo："all"（默认）、"selected" 或照片 id。"""
        return _text(edits.list_edits("all" if photo == "all" else _check_photo(photo), limit))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def lr_doctor() -> str:
        """Self-check: tests Lightroom, the plug-in, the token files, dependencies and the client registration one by one and says in
        Chinese what is wrong and what to do. Run it first when something does not work.

        自检：逐项检查 Lightroom、插件、口令文件、依赖和客户端登记，并用中文说明哪里有问题、怎么处理。哪里不对劲时先运行它。"""
        from . import doctor

        return doctor.format_report(doctor.run_checks(bridge, busy_message))

    return mcp
