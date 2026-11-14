# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Library browsing for the desktop app (v0.15): list the photos of a catalog folder, fetch thumbnails, select photos in Lightroom.

This is NOT an MCP tool and is not registered in ``tools.py``: only the desktop app on this computer may use it, an AI assistant
cannot. None of the three calls changes a photo or the catalog, so the read-only switch does not block them (selecting only
changes which photos Lightroom has selected). The plug-in re-checks every path and id; the checks here give clear errors early.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import urllib.parse
from typing import Callable

from .bridge import BridgeError, BridgeNotRun, BridgeTimeout

ID_RE = re.compile(r"[A-Za-z0-9\-]{1,64}")
MAX_LIST_LIMIT = 500
MAX_THUMB_IDS = 24
THUMB_MIN, THUMB_MAX = 64, 512
THUMB_MAX_BYTES = 150 * 1024
# The plug-in waits at most 8 s for a whole batch (+2 s for one smaller retry); the rest is for sending the pictures and for
# a command that is still running in front of this one. Before 1.1.1 it was 30 + 10 s per photo (up to 270 s).
THUMB_CALL_TIMEOUT = 40
MAX_SELECT_IDS = 50


class LibraryError(RuntimeError):
    """A request the desktop app made is wrong, or Lightroom did not answer in time (the message is for the user)."""


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_folder(path, what: str = "文件夹") -> str:
    """The folder must be a full local path (X:\\...), no network path, no "..", and an existing folder on this computer."""
    if (not isinstance(path, str) or not path.strip() or len(path) > 400 or re.search(r"[\x00-\x1f\x7f]", path)
            or path.startswith(("\\\\", "//")) or not re.match(r"^[A-Za-z]:[\\/]", path)):
        raise LibraryError(f"{what}要是本机文件夹的完整路径，比如 D:\\照片；网络路径（\\\\...）不允许。")
    if ".." in re.split(r"[\\/]+", path):
        raise LibraryError(f"{what}的路径里不能有 .. 。")
    if not os.path.isdir(path):
        raise LibraryError(f"这个{what}不存在，或者不是文件夹：{path}")
    return path


def _check_ids(ids, max_count: int, what: str = "ids") -> list[str]:
    if isinstance(ids, str):
        ids = [i for i in ids.split(",") if i]
    if not isinstance(ids, (list, tuple)) or not ids:
        raise LibraryError(f"{what} 要给出至少一个照片 id。")
    out: list[str] = []
    for i in ids:
        if not isinstance(i, str) or not ID_RE.fullmatch(i):
            raise LibraryError("照片 id 不合法：只能是字母、数字和连字符（1–64 个字符）。")
        if i not in out:
            out.append(i)
    if len(out) > max_count:
        raise LibraryError(f"一次最多 {max_count} 张照片。")
    return out


class LibraryService:
    """``call(command, params, timeout)`` is the bridge to the plug-in (``Bridge.call``)."""

    def __init__(self, call: Callable[..., dict]):
        self.call = call

    def _ask(self, command: str, params: dict, timeout: float) -> dict:
        try:
            return self.call(command, params, timeout=timeout)
        except (BridgeTimeout, BridgeNotRun) as e:   # read only: "not run" and "no answer" mean the same to the user
            raise LibraryError("Lightroom 没有在时限内回复，可能正忙。请稍后再试。") from e

    # ---- list the photos of a folder (read only) ----
    def list_folder_photos(self, path: str, recursive: bool = True, offset: int = 0, limit: int = 200) -> dict:
        """{"in_catalog", "total", "offset", "photos": [{id, name, path, subfolder, format, rating, flag, captured, width,
        height, is_virtual_copy}]}. A folder that is not in the catalog gives in_catalog=False and no photos (not an error)."""
        if not isinstance(recursive, bool):
            raise LibraryError("recursive 要么是 True 要么是 False。")
        if not _is_int(offset) or offset < 0:
            raise LibraryError("offset 不能是负数。")
        if not _is_int(limit) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise LibraryError(f"limit 要在 1 到 {MAX_LIST_LIMIT} 之间。")
        check_folder(path)
        params = {"path": urllib.parse.quote(path, safe=""), "recursive": "1" if recursive else "0",
                  "offset": str(offset), "limit": str(limit)}
        return self._ask("list_folder_photos", params, timeout=120)

    # ---- thumbnails (read only) ----
    def get_thumbnails(self, ids, size: int = 256) -> dict:
        """{"size", "thumbnails": [{id, ok, jpeg (bytes), width, height, bytes} | {id, ok: False, error}]}.

        error is "not_found", "timeout", "missing" (the original is offline or gone and Lightroom has no preview), "too_large"
        (over 150 KB even after one smaller retry), "bad_jpeg" (what came back is not a JPEG or not valid base64) or
        Lightroom's own message. Only JPEG data is ever returned."""
        id_list = _check_ids(ids, MAX_THUMB_IDS)
        if not _is_int(size) or not THUMB_MIN <= size <= THUMB_MAX:
            raise LibraryError(f"size 要在 {THUMB_MIN} 到 {THUMB_MAX} 之间。")
        data = self._ask("get_thumbnails", {"ids": urllib.parse.quote(",".join(id_list), safe=""), "size": str(size)},
                         timeout=THUMB_CALL_TIMEOUT)
        raw = data.get("thumbnails")
        if not isinstance(raw, list):
            raise BridgeError("插件返回的缩略图格式不对。")
        out = []
        for item in raw:
            if not isinstance(item, dict) or item.get("id") not in id_list:
                continue   # never pass on something that was not asked for
            if not item.get("ok"):
                out.append({"id": item["id"], "ok": False, "error": str(item.get("error") or "unknown")})
                continue
            try:
                jpeg = base64.b64decode(item.get("jpeg_base64") or "", validate=True)
            except (binascii.Error, ValueError, TypeError):
                out.append({"id": item["id"], "ok": False, "error": "bad_jpeg"})
                continue
            if jpeg[:2] != b"\xff\xd8":
                out.append({"id": item["id"], "ok": False, "error": "bad_jpeg"})
            elif len(jpeg) > THUMB_MAX_BYTES:
                out.append({"id": item["id"], "ok": False, "error": "too_large"})
            else:
                out.append({"id": item["id"], "ok": True, "jpeg": jpeg, "width": item.get("width"),
                            "height": item.get("height"), "bytes": len(jpeg)})
        return {"size": size, "thumbnails": out}

    # ---- select photos in Lightroom (changes the selection and optionally the folder shown, never a photo) ----
    def select_photos(self, ids, active: str | None = None, show_folder: str | None = None) -> dict:
        """Select the photos in Lightroom and read the selection back.

        {"status": "selected" | "partial" | "uncertain", "selected": [...], "missing": [...], "not_selected": [...],
         "all_selected", "folder_shown", "reason", "message"}. "partial": Lightroom selected fewer photos than found (they are
        not in the view it shows; pass show_folder). "uncertain": Lightroom did not answer in time, the selection may or may
        not have changed. Ids Lightroom cannot find are in "missing"; if none is found the plug-in refuses (BridgeError)."""
        id_list = _check_ids(ids, MAX_SELECT_IDS)
        params = {"ids": urllib.parse.quote(",".join(id_list), safe="")}
        if active is not None:
            if not isinstance(active, str) or not ID_RE.fullmatch(active) or active not in id_list:
                raise LibraryError("active 必须是 ids 里的某一个照片 id。")
            params["active"] = urllib.parse.quote(active, safe="")
        if show_folder is not None:
            check_folder(show_folder, "要显示的文件夹")
            params["show_folder"] = urllib.parse.quote(show_folder, safe="")
        try:
            data = self.call("select_photos", params, timeout=60)
        except BridgeTimeout as e:
            return {"status": "uncertain", "selected": [], "missing": [], "not_selected": [], "all_selected": False,
                    "folder_shown": None, "reason": None, "error": str(e),
                    "message": "Lightroom 没有在时限内回复，不确定选中有没有生效。请读一次当前选区再决定（不要急着重试）。"}
        status = "selected" if data.get("all_selected") else "partial"
        return {"status": status, **data}
