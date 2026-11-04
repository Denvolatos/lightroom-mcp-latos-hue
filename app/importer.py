# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导入：扫描来源文件夹 -> 复制到软件文件夹 -> 加入 Lightroom 目录。

原则：来源（例如相机存储卡）里的原片只读，绝不移动、删除、改动；软件文件夹里已有的文件绝不覆盖。
本模块不依赖界面和 Lightroom：加入目录的动作由调用方传入的函数完成（真实环境是插件命令 import_photo，测试里是假通道）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import threading
import time
from pathlib import Path

PHOTO_EXTS = frozenset("jpg jpeg arw cr2 cr3 nef nrw raf orf rw2 dng tif tiff heic heif png".split())   # 与插件一致
RAW_EXTS = frozenset("arw cr2 cr3 nef nrw raf orf rw2 dng".split())
JPEG_EXTS = frozenset("jpg jpeg".split())
SKIP_DIR_NAMES = frozenset(n.lower() for n in ("$RECYCLE.BIN", "System Volume Information"))
MAX_FILES = 5000
MAX_DEPTH = 6
CHUNK = 1024 * 1024
SPACE_MARGIN = 64 * 1024 * 1024         # 剩余空间需比待复制总量多出的余量
FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_REPARSE = 0x2, 0x4, 0x400
BUSY_MARKS = ("不能写入", "正忙")           # 插件在写入门没执行时的提示用语
BUSY_RETRIES, BUSY_WAIT = 3, 2.0
# 与插件 Commands.lua 的 BLOCKED_FOLDERS 一致：软件文件夹不能在这些位置（插件也会再校验）
BLOCKED_PARTS = ("/windows/", "/program files", "/programdata/", "/appdata/", "/.ssh/", "/lrmcp/", "/system/", "/library/",
                 "/usr/", "/bin/", "/sbin/", "/etc/", "/applications/", "/adobe/lightroom/modules")
RESERVED = frozenset(["con", "prn", "aux", "nul"] + [f"com{i}" for i in range(1, 10)] + [f"lpt{i}" for i in range(1, 10)])


def fmt_size(n: float) -> str:
    n = float(n)
    for unit, digits in (("B", 0), ("KB", 1), ("MB", 1), ("GB", 2)):
        if n < 1024:
            return f"{n:.{digits}f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def _contains(parent, child) -> bool:
    """child 等于 parent 或位于 parent 之内。"""
    a, b = _norm(parent), _norm(child)
    return b == a or b.startswith(a.rstrip("\\/") + os.sep)


def _real(p) -> str:
    try:
        return os.path.realpath(str(p))
    except OSError:
        return str(p)


def _attrs(st) -> int:
    return getattr(st, "st_file_attributes", 0)


def _is_link_or_reparse(st) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(_attrs(st) & FILE_ATTRIBUTE_REPARSE)


# ---------------------------------------------------------------- 校验
def validate_category(name) -> tuple[bool, str, str]:
    """分类文件夹名：留空=平铺。返回 (ok, 规范化后的名字, 中文原因)。"""
    if name is None:
        return True, "", ""
    if not isinstance(name, str):
        return False, "", "分类文件夹名无效。"
    n = name.strip()
    if not n:
        return True, "", ""
    if len(n) > 60:
        return False, n, "分类文件夹名过长（最多 60 个字符）。"
    if ".." in n:
        return False, n, "分类文件夹名不能包含“..”。"
    if re.search(r'[\\/:*?"<>|\x00-\x1f]', n):
        return False, n, "分类文件夹名不能包含 \\ / : * ? \" < > | 等字符，也不能包含路径。"
    if n.endswith((".", " ")) or n.startswith("."):
        return False, n, "分类文件夹名不能以点或空格开头或结尾。"
    if n.split(".")[0].lower() in RESERVED:
        return False, n, "分类文件夹名是系统保留名称，请换一个。"
    return True, n, ""


def check_folders(source: str, base: str, data_dir: Path | None = None) -> tuple[bool, str]:
    """来源文件夹与软件文件夹的关系校验。返回 (ok, 中文原因)。"""
    src, dst = str(source or ""), str(base or "")
    if not src or not dst:
        return False, "来源文件夹或软件文件夹未设置。"
    for a, b in ((src, dst), (_real(src), _real(dst))):
        if _contains(a, b) or _contains(b, a):
            return False, "来源文件夹与软件文件夹不能相同或互相包含。请选择相机存储卡上的文件夹，并确认软件文件夹在其他位置。"
    norm = (_norm(dst).replace("\\", "/") + "/").lower()
    for bad in BLOCKED_PARTS:
        if bad in norm:
            return False, "软件文件夹不能位于系统或程序目录、AppData 或本工具的数据目录内，请在设置中更换。"
    if data_dir is not None:
        for p in (src, dst, _real(dst)):
            if _contains(data_dir, p):
                return False, "不能使用本工具的数据目录作为来源或软件文件夹。"
        if _contains(dst, data_dir):
            return False, "软件文件夹不能包含本工具的数据目录。"
    return True, ""


def free_space(path) -> int | None:
    """path 所在磁盘的剩余字节数（路径不存在时取最近的已存在上级）；取不到返回 None。"""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return None


# ---------------------------------------------------------------- 扫描
def scan_folder(root, should_cancel=lambda: False, progress=None, max_files: int = MAX_FILES, max_depth: int = MAX_DEPTH) -> dict:
    """递归找照片。返回 {"files": [(路径, 大小)], "counts": {...}, "total_size", "truncated", "cancelled", "skipped_links", "error"}。
    只读：不改动任何文件。不跟随符号链接/联接点；跳过隐藏/系统目录与回收站等；深度上限 max_depth；达到 max_files 即停并标记 truncated。"""
    res = {"files": [], "counts": {"raw": 0, "jpeg": 0, "other": 0}, "total_size": 0, "truncated": False,
           "cancelled": False, "skipped_links": 0, "error": ""}
    root = str(root)
    stack = [(root, 0)]
    last_report = 0.0
    try:
        if not os.path.isdir(root):
            res["error"] = "所选路径不是文件夹或无法访问。"
            return res
        while stack:
            d, depth = stack.pop()
            if should_cancel():
                res["cancelled"] = True
                return res
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name.lower())
            except OSError:
                continue
            subdirs = []
            for e in entries:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                name = e.name
                if _is_link_or_reparse(st):
                    res["skipped_links"] += 1
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if depth >= max_depth or name.startswith(".") or name.lower() in SKIP_DIR_NAMES \
                            or _attrs(st) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                        continue
                    subdirs.append((e.path, depth + 1))
                    continue
                if not stat.S_ISREG(st.st_mode) or name.startswith(".") or _attrs(st) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in PHOTO_EXTS:
                    continue
                if len(res["files"]) >= max_files:
                    res["truncated"] = True
                    return res
                res["files"].append((e.path, st.st_size))
                res["total_size"] += st.st_size
                res["counts"]["raw" if ext in RAW_EXTS else "jpeg" if ext in JPEG_EXTS else "other"] += 1
            stack.extend(reversed(subdirs))             # 按名称顺序深入
            now = time.monotonic()
            if progress and now - last_report > 0.3:
                last_report = now
                progress(len(res["files"]))
    except OSError as e:
        res["error"] = f"读取文件夹失败：{e.strerror or e}"
    return res


# ---------------------------------------------------------------- 复制
class CopyResult(dict):
    """{"status": copied|skipped|failed, "dest", "reason"}"""


def _part_name(dest: Path, taken) -> Path:
    base = dest.name + ".part"
    for i in range(0, 10):
        p = dest.with_name(base if i == 0 else f"{base}{i + 1}")
        if not taken(p):
            return p
    return dest.with_name(base)


def _hash_file(path: Path) -> bytes:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.digest()


def _unchanged(path: Path, before) -> bool:
    after = path.lstat()
    return (not _is_link_or_reparse(after) and stat.S_ISREG(after.st_mode)
            and after.st_size == before.st_size and after.st_mtime_ns == before.st_mtime_ns
            and after.st_ino == before.st_ino and after.st_dev == before.st_dev)


def _unique_dest(src: Path, folder: Path, original) -> tuple[Path | None, bool]:
    """Only skip a same-name, same-size file when its content matches."""
    src_name, size = src.name, original.st_size
    source_hash = None
    stem, dot, ext = src_name.rpartition(".")
    if not dot:
        stem, ext = src_name, ""
    for n in range(1, 1000):
        name = src_name if n == 1 else f"{stem}_{n}" + (f".{ext}" if ext else "")
        cand = folder / name
        try:
            st = cand.lstat()
        except FileNotFoundError:
            return cand, False
        except OSError:
            return None, False
        if stat.S_ISREG(st.st_mode) and st.st_size == size and not _is_link_or_reparse(st):
            if source_hash is None:
                source_hash = _hash_file(src)
                if not _unchanged(src, original):
                    raise OSError("原文件在校验期间发生变化。")
            candidate_hash = _hash_file(cand)
            if not _unchanged(cand, st) or not _unchanged(src, original):
                raise OSError("文件在校验期间发生变化。")
            if source_hash == candidate_hash:
                return cand, True
    return None, False


def copy_one(src, folder, *, free_check=None) -> CopyResult:
    """把一个文件复制进 folder（必须已存在）。原文件只读。

    同名文件只有内容一致才跳过；不同内容自动改名。复制到临时文件并校验 SHA-256 后再改名。"""
    src, folder = Path(src), Path(folder)
    try:
        st = src.lstat()
    except OSError as e:
        return CopyResult(status="failed", dest="", reason=f"无法读取原文件：{e.strerror or e}")
    if _is_link_or_reparse(st) or not stat.S_ISREG(st.st_mode):
        return CopyResult(status="failed", dest="", reason="原文件不是普通文件（可能是快捷方式或链接），已跳过。")
    size = st.st_size
    try:
        dest, exists = _unique_dest(src, folder, st)
    except OSError as e:
        return CopyResult(status="failed", dest="", reason=f"校验失败：{e.strerror or e}")
    if dest is None:
        return CopyResult(status="failed", dest="", reason="无法确定不重名的目标文件名。")
    if exists:
        return CopyResult(status="skipped", dest=str(dest), reason="软件文件夹里已有同名且内容一致的文件，视为已导入。")
    if free_check is not None:
        free = free_check()
        if free is not None and free < size + SPACE_MARGIN // 8:
            return CopyResult(status="failed", dest="", reason="目标磁盘空间不足。")
    part = _part_name(dest, lambda p: p.exists())
    created = False
    try:
        digest = hashlib.sha256()
        with open(src, "rb") as fi:
            fo = open(part, "xb")                    # 独占创建：已有同名文件时报错而不是覆盖
            created = True
            with fo:
                while True:
                    buf = fi.read(CHUNK)
                    if not buf:
                        break
                    fo.write(buf)
                    digest.update(buf)
        got = part.stat().st_size
        if got != size or not _unchanged(src, st):
            raise OSError("复制后文件大小与原文件不一致，或原文件在复制期间发生了变化。")
        if _hash_file(part) != digest.digest() or not _unchanged(src, st):
            raise OSError("复制后的内容校验失败，或原文件在校验期间发生了变化。")
        try:
            os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns))     # 保留拍摄/修改时间
        except OSError:
            pass
        if dest.exists():
            raise OSError("目标文件名已被占用，未覆盖。")
        os.rename(part, dest)                        # Windows 上目标存在会报错，不会覆盖
        return CopyResult(status="copied", dest=str(dest), reason="")
    except OSError as e:
        if created:
            try:
                part.unlink()
            except OSError:
                pass
        reason = e.strerror or str(e)
        if getattr(e, "errno", None) == 28:
            reason = "目标磁盘空间不足。"
        return CopyResult(status="failed", dest="", reason=f"复制失败：{reason}")


# ---------------------------------------------------------------- 加入 Lightroom
LR_LABEL = {"imported": "已加入", "already": "已加入", "uncertain": "需确认", "failed": "加入失败", "pending": "尚未加入"}


def add_to_lightroom(path: str, import_fn, *, sleep=time.sleep) -> dict:
    """调用 import_fn(path)（返回 {"status": imported|already|uncertain, "message"}）。Lightroom 忙时等待后有限次重试；
    uncertain 不重试（避免重复添加）。返回 {"lr": imported|already|uncertain|failed|pending, "reason"}。"""
    for attempt in range(BUSY_RETRIES + 1):
        try:
            r = import_fn(path)
        except Exception as e:                      # noqa: BLE001 - 翻成中文原因
            name, msg = type(e).__name__, str(e)
            if name == "PluginNotConnected":
                return {"lr": "pending", "reason": "Lightroom 未连接。"}
            if name == "ReadOnlyError":
                return {"lr": "failed", "reason": "只读模式已开启，不能加入 Lightroom。"}
            if name == "BridgeTimeout":
                return {"lr": "uncertain", "reason": "Lightroom 未在规定时间内响应，请在 Lightroom 中确认该照片是否已加入。"}
            if any(m in msg for m in BUSY_MARKS) and attempt < BUSY_RETRIES:
                sleep(BUSY_WAIT)
                continue
            return {"lr": "failed", "reason": ("Lightroom 繁忙，多次重试后仍未加入。" if any(m in msg for m in BUSY_MARKS)
                                               else f"Lightroom 拒绝了该文件：{msg}")[:300]}
        status = (r or {}).get("status")
        if status in ("imported", "already"):
            return {"lr": status, "reason": ""}
        if status == "uncertain":
            return {"lr": "uncertain", "reason": "Lightroom 未在规定时间内响应，请在 Lightroom 中确认该照片是否已加入。"}
        return {"lr": "failed", "reason": "Lightroom 返回了无法识别的结果。"}
    return {"lr": "failed", "reason": "Lightroom 繁忙，多次重试后仍未加入。"}


# ---------------------------------------------------------------- 导入任务
class ImportJob:
    """顺序处理：逐个文件 复制 -> 加入 Lightroom。cancel() 后在当前文件处理完停止。"""

    def __init__(self, files, folder, *, import_fn=None, connected=lambda: True, emit=lambda ev: None,
                 clock=time.monotonic, sleep=time.sleep, free_check=None, mode="import"):
        self.files = list(files)                 # [(源路径, 大小)]；mode="retry" 时是 [(已复制的目标路径, 大小)]
        self.folder = Path(folder)
        self.import_fn, self.connected, self.emit = import_fn, connected, emit
        self._clock, self._sleep, self._free = clock, sleep, free_check
        self.mode = mode
        self.items: list[dict] = []
        self._cancel = threading.Event()
        self.state = "idle"                      # idle|running|done
        self.cancelled = False
        self.started = 0.0
        self.elapsed = 0.0
        self.current = ""
        self.done_count = 0
        self._thread: threading.Thread | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        self.state = "running"
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def counts(self) -> dict:
        c = {"copied": 0, "skipped": 0, "failed": 0, "lr_ok": 0, "lr_uncertain": 0, "lr_pending": 0, "lr_failed": 0}
        for it in self.items:
            if it["copy"] in ("copied", "skipped", "failed"):
                c[it["copy"]] += 1
            lr = it.get("lr")
            if lr in ("imported", "already"):
                c["lr_ok"] += 1
            elif lr == "uncertain":
                c["lr_uncertain"] += 1
            elif lr == "pending":
                c["lr_pending"] += 1
            elif lr == "failed":
                c["lr_failed"] += 1
        return c

    def snapshot(self) -> dict:
        el = (self._clock() - self.started) if self.state == "running" else self.elapsed
        return {"state": self.state, "i": self.done_count, "n": len(self.files), "name": self.current,
                "elapsed": round(el, 1), "counts": self.counts(), "cancelled": self.cancelled, "mode": self.mode}

    def _progress(self) -> None:
        self.emit({"type": "import_progress", **self.snapshot()})

    def run(self) -> None:
        self.started = self._clock()
        self.state = "running"
        try:
            for idx, (path, size) in enumerate(self.files):
                if self._cancel.is_set():
                    self.cancelled = True
                    break
                name = Path(path).name
                self.current = name
                self._progress()
                item = {"name": name, "src": str(path), "dest": "", "copy": "", "lr": "none", "reason": ""}
                if self.mode == "retry":
                    item.update(copy="copied", dest=str(path))
                else:
                    r = copy_one(path, self.folder, free_check=self._free)
                    item.update(copy=r["status"], dest=r["dest"], reason=r["reason"] if r["status"] == "failed" else "")
                if item["copy"] in ("copied", "skipped") and self.import_fn is not None:
                    if not self.connected():
                        item.update(lr="pending", reason="Lightroom 未连接，尚未加入。")
                    else:
                        lr = add_to_lightroom(item["dest"], self.import_fn, sleep=self._sleep)
                        item.update(lr=lr["lr"], reason=lr["reason"])
                elif item["copy"] in ("copied", "skipped"):
                    item.update(lr="pending", reason="Lightroom 未连接，尚未加入。")
                self.items.append(item)
                self.done_count = idx + 1
        finally:
            self.elapsed = self._clock() - self.started
            self.current = ""
            self.state = "done"
            self.emit({"type": "import_done", **self.result()})

    def result(self) -> dict:
        problems = [{"name": it["name"], "copy": it["copy"], "lr": it["lr"], "reason": it["reason"]}
                    for it in self.items if it["copy"] == "failed" or it["lr"] in ("failed", "uncertain", "pending")]
        snap = self.snapshot()
        snap["problems"] = problems[:300]
        snap["problems_more"] = max(0, len(problems) - 300)
        snap["pending_retry"] = sum(1 for it in self.items if it["lr"] == "pending")
        return snap

    def pending_files(self) -> list[tuple[str, int]]:
        """已复制但尚未加入 Lightroom 的目标文件（供“重新尝试加入”）。"""
        out = []
        for it in self.items:
            if it["lr"] == "pending" and it["dest"]:
                try:
                    out.append((it["dest"], os.path.getsize(it["dest"])))
                except OSError:
                    pass
        return out


# ---------------------------------------------------------------- 软件文件夹目录树（只读）
def library_tree(base, limit: int = 300) -> dict:
    """软件文件夹的只读目录：{"exists", "total", "groups": [{"name", "count", "files": [{"name","size"}]}], "shown", "more"}。
    第一层：根目录下的照片归“（未分类）”，每个子文件夹为一个分类；只列到两层，.part 与非照片文件不计。"""
    base = Path(base)
    out = {"exists": base.is_dir(), "total": 0, "groups": [], "shown": 0, "more": 0}
    if not out["exists"]:
        return out
    groups: dict[str, list] = {}

    def photos(folder: Path) -> list:
        res = []
        try:
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISREG(st.st_mode) and "." in e.name and e.name.rsplit(".", 1)[-1].lower() in PHOTO_EXTS:
                        res.append({"name": e.name, "size": st.st_size})
        except OSError:
            pass
        return sorted(res, key=lambda f: f["name"].lower())

    root_files = photos(base)
    if root_files:
        groups["（未分类）"] = root_files
    try:
        with os.scandir(base) as it:
            dirs = sorted((e for e in it if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")),
                          key=lambda e: e.name.lower())
    except OSError:
        dirs = []
    for e in dirs:
        fs = photos(Path(e.path))
        if fs:
            groups[e.name] = fs
    shown = 0
    for name, fs in groups.items():
        out["total"] += len(fs)
        room = max(0, limit - shown)
        keep = fs[:room]
        shown += len(keep)
        out["groups"].append({"name": name, "count": len(fs), "files": keep})
    out["shown"] = shown
    out["more"] = out["total"] - shown
    return out
