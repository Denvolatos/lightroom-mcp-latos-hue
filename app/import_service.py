"""导入功能的后台总管：选来源文件夹 -> 后台扫描 -> 确认信息 -> 后台复制并加入 Lightroom。界面进程里只有一个实例。

路径只来自用户在系统对话框里的这一次选择（Api.choose_source_folder），页面传来的任意路径一律不接受。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import importer as imp
import settings as appsettings

DATA_DIR = Path.home() / "LrMcp"


class ImportService:
    def __init__(self, settings, lr, emit, *, data_dir: Path = DATA_DIR, free_fn=imp.free_space, scan_fn=imp.scan_folder,
                 clock=time.monotonic, sleep=time.sleep, job_cls=imp.ImportJob):
        self.settings, self.lr, self.emit = settings, lr, emit
        self.data_dir, self._free, self._scan_fn = Path(data_dir), free_fn, scan_fn
        self._clock, self._sleep, self._job_cls = clock, sleep, job_cls
        self._lock = threading.Lock()
        self.stage = "idle"                      # idle | scanning | ready | copying | done
        self.source = ""
        self.scan: dict | None = None
        self.job: imp.ImportJob | None = None
        self._scan_cancel = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self.last_result: dict | None = None

    # ---- 入口检查 --------------------------------------------------
    def readonly_message(self) -> str | None:
        try:
            m = self.lr.readonly_error()
        except Exception:
            m = None
        return ("只读模式已开启，无法导入照片。请先关闭只读模式（删除只读开关文件）后再试。" if m else None)

    def begin(self) -> dict:
        """点“导入”后、弹出文件夹对话框之前的检查。"""
        if self.stage in ("scanning", "copying"):
            return {"ok": False, "message": "正在扫描或导入，请等待完成或先取消。"}
        m = self.readonly_message()
        if m:
            return {"ok": False, "message": m}
        return {"ok": True, "message": ""}

    # ---- 扫描 ------------------------------------------------------
    def set_source(self, path: str) -> dict:
        """用户选定来源文件夹，开始后台扫描。"""
        b = self.begin()
        if not b["ok"]:
            return b
        p = str(path or "")
        if not p or not Path(p).is_dir():
            return {"ok": False, "message": "所选路径不是可访问的文件夹。"}
        with self._lock:
            self.source = p
            self.scan = None
            self.last_result = None
            self.job = None
            self.stage = "scanning"
            self._scan_cancel = threading.Event()
        self.emit({"type": "import_scan", "state": "scanning", "found": 0})
        cancel = self._scan_cancel
        self._scan_thread = threading.Thread(target=self._do_scan, args=(p, cancel), daemon=True)
        self._scan_thread.start()
        return {"ok": True, "message": ""}

    def _do_scan(self, p: str, cancel: threading.Event) -> None:
        try:
            res = self._scan_fn(p, should_cancel=cancel.is_set,
                                progress=lambda n: self.emit({"type": "import_scan", "state": "scanning", "found": n}))
        except Exception as e:                   # noqa: BLE001
            res = {"files": [], "counts": {"raw": 0, "jpeg": 0, "other": 0}, "total_size": 0, "truncated": False,
                   "cancelled": False, "skipped_links": 0, "error": f"扫描失败：{e}"}
        with self._lock:
            if cancel.is_set() or self.stage != "scanning":
                self.stage = "idle"
                self.scan = None
                self.emit({"type": "import_scan", "state": "cancelled"})
                return
            self.scan = res
            self.stage = "ready"
        self.emit({"type": "import_scan", "state": "done", "info": self._found(res), "error": res.get("error", "")})

    @staticmethod
    def _found(res: dict) -> dict:
        c = res["counts"]
        return {"n": len(res["files"]), "raw": c["raw"], "jpeg": c["jpeg"], "other": c["other"], "total_size": res["total_size"],
                "size_text": imp.fmt_size(res["total_size"]), "truncated": res["truncated"], "skipped_links": res["skipped_links"]}

    # ---- 确认信息 --------------------------------------------------
    def prepare(self, category="") -> dict:
        """扫描完成后、用户点“开始导入”之前：汇总数量、目标位置、剩余空间，并给出是否允许开始。"""
        with self._lock:
            scan, source = self.scan, self.source
        if scan is None:
            return {"ok": False, "can_start": False, "errors": {"_": "尚无扫描结果，请重新选择来源文件夹。"}}
        errors: dict[str, str] = {}
        found = self._found(scan)
        if scan.get("error"):
            errors["_"] = scan["error"]
        if found["n"] == 0 and not scan.get("error"):
            errors["count"] = "所选文件夹中没有找到照片。"
        if scan["truncated"]:
            errors["count"] = f"照片数量超过 {imp.MAX_FILES} 张，请选择其中的子文件夹分批导入。"
        ok_cat, cat, why = imp.validate_category(category)
        if not ok_cat:
            errors["category"] = why
        base = self.settings.data["base_folder"]
        v = appsettings.validate_folder(base)
        base_exists = bool(v["ok"] and v["exists"])
        if not v["ok"]:
            errors["base"] = "软件文件夹不可用：" + v["message"] + "请在设置中更换。"
        else:
            base = v["path"]
            ok_rel, why_rel = imp.check_folders(source, base, self.data_dir)
            if not ok_rel:
                errors["base"] = why_rel
        folder = Path(base) / cat if (ok_cat and cat) else Path(base)
        free = self._free(base) if v["ok"] else None
        needed = scan["total_size"]
        shortfall = 0
        if free is not None and found["n"] and free < needed + imp.SPACE_MARGIN:
            shortfall = needed + imp.SPACE_MARGIN - free
            errors["space"] = f"目标磁盘剩余空间不足，还差 {imp.fmt_size(shortfall)}。请清理磁盘或在设置中更换软件文件夹。"
        if free is None and v["ok"]:
            errors["space"] = "无法读取目标磁盘的剩余空间，暂不能开始。"
        return {"ok": not errors, "can_start": not errors, "errors": errors, "found": found, "source": source,
                "base": base, "base_exists": base_exists, "base_is_default": base == appsettings.default_base_folder(),
                "category": cat, "target": str(folder), "free": free, "free_text": imp.fmt_size(free) if free is not None else "未知",
                "needed_text": imp.fmt_size(needed), "shortfall": shortfall, "lr_connected": bool(self.lr.connected)}

    # ---- 开始 ------------------------------------------------------
    def start(self, category="", create_base: bool = False) -> dict:
        m = self.readonly_message()
        if m:
            return {"ok": False, "message": m}
        with self._lock:
            if self.stage != "ready":
                return {"ok": False, "message": "当前没有可导入的内容，请先选择来源文件夹。"}
        info = self.prepare(category)
        if not info["can_start"]:
            return {"ok": False, "message": next(iter(info["errors"].values()), "无法开始导入。")}
        base = Path(info["base"])
        if not info["base_exists"]:
            if not create_base:
                return {"ok": False, "needs_create": True, "message": f"软件文件夹尚不存在：{base}", "base": str(base)}
            c = appsettings.create_folder(str(base))
            if not c["ok"]:
                return {"ok": False, "message": c["message"]}
        folder = Path(info["target"])
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "message": f"无法创建目标文件夹：{e.strerror or e}"}
        if not imp._contains(imp._real(base), imp._real(folder)):        # 防止分类名指向别处（例如已存在的联接点）
            return {"ok": False, "message": "目标位置不在软件文件夹之内，已拒绝。"}
        job = self._job_cls(self.scan["files"], folder, import_fn=self.lr.import_photo, connected=lambda: bool(self.lr.connected),
                            emit=self._job_event, clock=self._clock, sleep=self._sleep,
                            free_check=lambda: self._free(folder))
        with self._lock:
            self.job = job
            self.stage = "copying"
        job.start()
        return {"ok": True, "message": ""}

    def _job_event(self, ev: dict) -> None:
        if ev.get("type") == "import_done":
            with self._lock:
                self.stage = "done"
                self.last_result = {k: v for k, v in ev.items() if k != "type"}
        self.emit(ev)

    # ---- 取消 / 重试 -----------------------------------------------
    def cancel(self) -> dict:
        with self._lock:
            stage, job = self.stage, self.job
        if stage == "scanning":
            self._scan_cancel.set()
            with self._lock:
                self.stage = "idle"
            return {"ok": True}
        if stage == "copying" and job is not None:
            job.cancel()
            return {"ok": True}
        if stage == "ready":
            with self._lock:
                self.stage = "idle"
                self.scan = None
            return {"ok": True}
        return {"ok": False}

    def close(self) -> dict:
        """关闭结果界面。"""
        with self._lock:
            if self.stage in ("done", "ready", "idle"):
                self.stage = "idle"
                self.scan = None
        return {"ok": True}

    def retry_lr(self) -> dict:
        """对已复制但尚未加入 Lightroom 的文件再跑一遍加入。"""
        m = self.readonly_message()
        if m:
            return {"ok": False, "message": m}
        with self._lock:
            if self.stage != "done" or self.job is None:
                return {"ok": False, "message": "没有可重新加入的文件。"}
            files = self.job.pending_files()
            prev = self.job
        if not files:
            return {"ok": False, "message": "没有尚未加入 Lightroom 的文件。"}
        if not self.lr.connected:
            return {"ok": False, "message": "Lightroom 仍未连接。请确认 Lightroom 已打开且插件已启用后重试。"}
        job = self._job_cls(files, prev.folder, import_fn=self.lr.import_photo, connected=lambda: bool(self.lr.connected),
                            emit=lambda ev: self._retry_event(ev, prev), clock=self._clock, sleep=self._sleep, mode="retry")
        with self._lock:
            self.job = job
            self.stage = "copying"
        job.start()
        return {"ok": True, "message": ""}

    def _retry_event(self, ev: dict, prev) -> None:
        """重试任务的事件：结束时把结果并回上一次的总结果，页面看到的仍是完整汇总。"""
        if ev.get("type") != "import_done":
            self.emit(ev)
            return
        with self._lock:
            retry_job = self.job
            by_dest = {it["dest"]: it for it in prev.items}
            for it in (retry_job.items if retry_job is not None else []):
                old = by_dest.get(it["dest"])
                if old is not None:
                    old["lr"], old["reason"] = it["lr"], it["reason"]
            self.job = prev
            self.stage = "done"
            res = prev.result()
            res["retried"] = True
            self.last_result = res
        self.emit({"type": "import_done", **res})

    # ---- 状态（页面加载/补齐用） ------------------------------------
    def state(self) -> dict:
        with self._lock:
            out = {"stage": self.stage, "source": self.source}
            if self.scan is not None:
                out["found"] = self._found(self.scan)
                out["scan_error"] = self.scan.get("error", "")
            if self.job is not None and self.stage == "copying":
                out["progress"] = self.job.snapshot()
            if self.last_result is not None and self.stage == "done":
                out["result"] = self.last_result
        return out

    # ---- 软件文件夹（只读） -----------------------------------------
    def library(self, limit: int = 300) -> dict:
        base = self.settings.data["base_folder"]
        tree = imp.library_tree(base, limit=max(1, min(int(limit), 2000)))
        tree["base"] = str(base)
        return tree
