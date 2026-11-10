# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导出功能后台：把 Lightroom 中当前选中的那张照片（含已做的调整）导出为 JPEG 或 TIFF。

安全约定：
- 导出文件夹只来自用户在系统文件夹对话框里的这一次点击（Api.choose_export_folder -> set_folder），保存在后端；
  Api.export_current_photo(options) 不接受页面传来的路径，只用后端记住的那一个。
- "在资源管理器中显示"只对本次导出得到的结果文件有效，路径来自后端记录，不来自页面。
- 页面传来的所有选项在这里重新校验（格式、位深、长边、质量、元数据）。
- 导出不修改照片，因此不受只读开关拦截；"逐项确认"开关与导出无关。
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

import importer as imp
import settings as appsettings
from lr_service import patient

DATA_DIR = Path.home() / "LrMcp"
EXPORT_TIMEOUT = 120.0          # 秒；超过按"状态不确定"处理
FMT_LABEL = {"jpeg": "JPEG", "tiff": "TIFF"}
EXT = {"jpeg": "jpg", "tiff": "tif"}
BIG_TIFF_NOTE = "文件可能超过 100 MB。"

UNCERTAIN_MSG = "Lightroom 没有在时限内回复，不确定是否已导出成功。请到所选文件夹确认是否有新文件，确认前请勿重复导出。"


def fmt_size(n) -> str:
    return imp.fmt_size(n)


# ---------------------------------------------------------------- 选项与文件夹校验
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_options(opts) -> tuple[dict | None, str]:
    """校验页面传来的导出选项。返回 (规范化后的选项, "") 或 (None, 中文原因)。忽略未知字段（包括任何路径字段）。"""
    if not isinstance(opts, dict):
        return None, "导出选项无效。"
    fmt = opts.get("format")
    if not isinstance(fmt, str) or fmt not in appsettings.EXPORT_FORMATS:
        return None, "格式只能选择 JPEG 或 TIFF。"
    size = opts.get("size", 0)
    lo, hi = appsettings.EXPORT_EDGE_RANGE
    if not _is_int(size) or (size != 0 and not lo <= size <= hi):
        return None, f"自定义大小需为 {lo} 到 {hi} 之间的整数（像素）。"
    q = opts.get("quality", 92)
    qlo, qhi = appsettings.EXPORT_QUALITY_RANGE
    if not _is_int(q) or not qlo <= q <= qhi:
        return None, f"质量需在 {qlo} 到 {qhi} 之间。"
    bd = opts.get("bit_depth", 16)
    if not _is_int(bd) or bd not in appsettings.EXPORT_BIT_DEPTHS:
        return None, "位深只能选择 8 位或 16 位。"
    md = opts.get("metadata", "minimal")
    if not isinstance(md, str) or md not in appsettings.EXPORT_METADATA:
        return None, "元数据选项无效。"
    return {"format": fmt, "size": size, "quality": q, "bit_depth": bd, "metadata": md}, ""


def check_export_folder(path) -> tuple[bool, str, str]:
    """导出文件夹校验：本机绝对路径、已存在的文件夹、可写、不在系统/程序目录与本工具数据目录。返回 (ok, 中文原因, 规范路径)。"""
    raw = path if isinstance(path, str) else ""
    if not raw.strip() or len(raw) > 400 or re.search(r"[\x00-\x1f\x7f]", raw):
        return False, "请选择导出文件夹。", ""
    v = appsettings.validate_folder(raw)
    if not v["ok"]:
        return False, v["message"], ""
    p = v["path"]
    if not v["exists"]:
        return False, "所选文件夹不存在，请重新选择。", ""
    for q in (p, imp._real(p)):
        norm = (q.replace("\\", "/").lower().rstrip("/") + "/")
        if any(bad in norm for bad in imp.BLOCKED_PARTS):
            return False, "不能导出到系统或程序目录、AppData 或本工具的数据目录，请选择其他位置。", ""
        if imp._contains(DATA_DIR, q):
            return False, "不能导出到本工具的数据目录，请选择其他位置。", ""
    return True, "", p


def preview_name(photo_name: str | None, fmt: str, size: int) -> str:
    """文件名预览，规则与插件一致：<照片名>_LrMCP_<full|N px>.<jpg|tif>（照片名只保留字母数字、- 和 _，其余换成 _）。"""
    leaf = os.path.basename(str(photo_name or "photo").replace("\\", "/"))
    stem = os.path.splitext(leaf)[0]
    base = re.sub(r"[^A-Za-z0-9\-_]", "_", stem) or "photo"
    tag = f"{size}px" if size else "full"
    return f"{base}_LrMCP_{tag}.{EXT.get(fmt, 'jpg')}"


def photo_summary(detail: dict | None) -> dict:
    i = (detail or {}).get("info") or {}
    size = f"{i['width']} × {i['height']}" if i.get("width") and i.get("height") else None
    return {"name": (detail or {}).get("name") or i.get("name"), "camera": i.get("camera"), "format": i.get("format"),
            "size": size, "iso": i.get("iso"), "aperture": i.get("aperture"), "shutter": i.get("shutter_speed"),
            "focal": i.get("focal_length")}


def reveal_in_explorer(path: str) -> None:
    """explorer /select：不经 shell，路径作为单个参数。"""
    subprocess.Popen(["explorer", "/select," + path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ---------------------------------------------------------------- 服务
class ExportService:
    def __init__(self, settings, lr, emit, *, timeout: float = EXPORT_TIMEOUT, reveal_fn=reveal_in_explorer):
        self.settings, self.lr, self.emit = settings, lr, emit
        self.timeout, self._reveal = timeout, reveal_fn
        self._lock = threading.Lock()
        self.stage = "idle"                    # idle | running | done
        self.folder = ""                       # 后端记住的导出文件夹（只由 set_folder 写入，或启动时取自设置并复验）
        self.last_result: dict | None = None
        self.last_file = ""                    # 本次导出得到的结果文件（只有它能被"显示"）
        self._shown_id: str | None = None      # 对话框打开时显示的那张照片的 id

    # ---- 文件夹 ----------------------------------------------------
    def set_folder(self, path: str) -> dict:
        """用户在系统对话框里选定文件夹。通过校验才记住，并写入设置（下次作为默认）。"""
        ok, msg, p = check_export_folder(path)
        if not ok:
            return {"ok": False, "message": msg}
        with self._lock:
            self.folder = p
        try:
            self.settings.update({"export_last_folder": p})
        except Exception:                       # 记不住不影响本次导出
            pass
        return {"ok": True, "message": "", "folder": p}

    def _folder_now(self) -> tuple[str, str]:
        """当前可用的导出文件夹（后端记忆优先，其次设置里上次选的；都要复验）。返回 (路径, 提示)。"""
        cand = self.folder or self.settings.data.get("export_last_folder", "")
        if not cand:
            return "", "请选择保存位置。"
        ok, msg, p = check_export_folder(cand)
        if not ok:
            with self._lock:
                self.folder = ""
            return "", "之前选择的文件夹已不可用（" + msg.rstrip("。") + "），请重新选择。"
        return p, ""

    # ---- 对话框状态 ------------------------------------------------
    def options_from_settings(self) -> dict:
        d = self.settings.data
        return {"format": d.get("export_format", "jpeg"), "size": d.get("export_size", 0), "quality": d.get("export_quality", 92),
                "bit_depth": d.get("export_bit_depth", 16), "metadata": d.get("export_metadata", "minimal")}

    def dialog_state(self) -> dict:
        """打开导出对话框时：照片、文件夹、默认选项、能否导出。"""
        with self._lock:
            stage = self.stage
        out = {"stage": stage, "options": self.options_from_settings(), "connected": bool(self.lr.connected),
               "photo": None, "folder": "", "folder_message": "", "can_export": False, "reason": ""}
        folder, fmsg = self._folder_now()
        out["folder"], out["folder_message"] = folder, fmsg
        if stage == "running":
            out["reason"] = "正在导出，请等待完成。"
            return out
        if not out["connected"]:
            out["reason"] = "Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。"
            return out
        detail = None
        try:
            with patient(self.lr):                  # 用户点开导出对话框：可以等，用长超时
                detail = self.lr.selected_detail()
        except Exception:
            detail = None
        if detail is None:
            out["reason"] = "无法读取 Lightroom 中选中的照片，请稍后重试。"
            return out
        if not detail.get("id"):
            out["reason"] = "Lightroom 中没有选中照片。请先选择一张照片。"
            self._shown_id = None
            return out
        self._shown_id = detail["id"]
        out["photo"] = photo_summary(detail)
        out["can_export"] = bool(folder)
        if not folder:
            out["reason"] = fmsg
        return out

    # ---- 导出 ------------------------------------------------------
    def export(self, options) -> dict:
        """点"导出"：校验后在后台线程执行；立刻返回 {"ok"}，结果经 export_done 事件和 state() 给出。"""
        opts, why = validate_options(options)
        if opts is None:
            return {"ok": False, "message": why}
        with self._lock:
            if self.stage == "running":
                return {"ok": False, "message": "正在导出，请等待完成。"}
        if not self.lr.connected:
            return {"ok": False, "message": "Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。"}
        folder, fmsg = self._folder_now()
        if not folder:
            return {"ok": False, "message": fmsg}
        try:
            with patient(self.lr):
                detail = self.lr.selected_detail()
        except Exception:
            detail = None
        if detail is None:
            return {"ok": False, "message": "无法读取 Lightroom 中选中的照片，请稍后重试。"}
        pid = detail.get("id")
        if not pid:
            return {"ok": False, "message": "Lightroom 中没有选中照片。请先选择一张照片。"}
        if self._shown_id is not None and pid != self._shown_id:
            return {"ok": False, "changed": True, "message": "Lightroom 中选中的照片已变化。请关闭对话框后重新打开，确认要导出的照片。"}
        # 记住本次选择（作为下次默认）
        try:
            self.settings.update({"export_format": opts["format"], "export_size": opts["size"], "export_quality": opts["quality"],
                                  "export_bit_depth": opts["bit_depth"], "export_metadata": opts["metadata"]})
        except Exception:
            pass
        photo = photo_summary(detail)
        with self._lock:
            self.stage = "running"
            self.last_result = None
            self.last_file = ""
        self.emit({"type": "export_progress", "state": "running"})
        threading.Thread(target=self._run, args=(opts, folder, pid, photo), daemon=True).start()
        return {"ok": True, "message": ""}

    def _call(self, opts: dict, folder: str, pid: str, box: dict, done: threading.Event) -> None:
        try:
            box["data"] = self.lr.export_photo(folder, opts["format"], opts["size"], opts["quality"], opts["metadata"],
                                               opts["bit_depth"], photo=pid)
        except Exception as e:                  # noqa: BLE001
            box["error"] = e
        finally:
            done.set()

    def _run(self, opts: dict, folder: str, pid: str, photo: dict) -> None:
        box: dict = {}
        done = threading.Event()
        threading.Thread(target=self._call, args=(opts, folder, pid, box, done), daemon=True).start()
        t0 = time.monotonic()
        finished = done.wait(self.timeout)
        res = self._result(opts, folder, photo, box if finished else None, time.monotonic() - t0)
        with self._lock:
            self.stage = "done"
            self.last_result = res
            self.last_file = res.get("path", "") if res["status"] == "exported" else ""
        self.emit({"type": "export_done", **self.public(res)})

    @staticmethod
    def public(res: dict) -> dict:
        """给页面的结果：去掉结果文件的完整路径（文件夹与文件名分开显示；显示文件只能由后端记录的路径执行）。"""
        return {k: v for k, v in res.items() if k != "path"}

    def _result(self, opts: dict, folder: str, photo: dict, box: dict | None, elapsed: float) -> dict:
        base = {"format": opts["format"], "format_label": FMT_LABEL[opts["format"]], "folder": folder,
                "photo_name": photo.get("name"), "elapsed": round(elapsed, 1)}
        if box is None:
            return {**base, "status": "uncertain", "message": UNCERTAIN_MSG}
        if "error" in box:
            return {**base, "status": "failed", "message": self.explain(box["error"])}
        data = box.get("data") or {}
        if data.get("status") == "uncertain":
            return {**base, "status": "uncertain", "message": UNCERTAIN_MSG}
        path = str(data.get("path") or "")
        # 结果文件必须在所选文件夹内且确实存在，否则不当作成功
        if not path or not imp._contains(folder, os.path.dirname(path)) or not os.path.isfile(path):
            return {**base, "status": "failed", "message": "Lightroom 报告已导出，但在所选文件夹中没有找到结果文件。请到文件夹确认。"}
        size = os.path.getsize(path)
        w, h = data.get("width"), data.get("height")
        return {**base, "status": "exported", "message": "", "path": path, "file": os.path.basename(path), "bytes": size,
                "size_text": fmt_size(size), "width": w, "height": h, "dimensions": f"{w} × {h}" if w and h else None,
                "bit_depth": data.get("bit_depth"), "quality": data.get("quality"), "metadata": opts["metadata"]}

    @staticmethod
    def explain(e: Exception) -> str:
        name = type(e).__name__
        msg = str(e).strip()
        if name == "PluginNotConnected":
            return "Lightroom 插件未连接。请确认 Lightroom 已打开且插件已启用。"
        if name == "BridgeTimeout":
            return UNCERTAIN_MSG
        if name in ("EditError", "BridgeError") and msg:
            return msg                           # 服务端/插件抛出的中文提示直接使用
        return "导出失败：" + (msg or name)

    # ---- 状态 / 显示 / 关闭 ----------------------------------------
    def state(self) -> dict:
        with self._lock:
            out = {"stage": self.stage}
            if self.stage == "done" and self.last_result is not None:
                out["result"] = self.public(self.last_result)
        return out

    def reveal_last(self) -> dict:
        """在资源管理器中选中本次导出得到的结果文件；没有结果或文件已不存在时拒绝。"""
        with self._lock:
            path = self.last_file
        if not path:
            return {"ok": False, "message": "没有可显示的导出文件。"}
        if not os.path.isfile(path):
            return {"ok": False, "message": "该导出文件已不存在。"}
        try:
            self._reveal(path)
        except (OSError, AttributeError) as e:
            return {"ok": False, "message": f"无法打开资源管理器：{e}"}
        return {"ok": True, "message": ""}

    def close(self) -> dict:
        with self._lock:
            if self.stage == "done":
                self.stage = "idle"
        return {"ok": True}
