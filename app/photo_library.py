# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件内的图库：在软件里浏览、选择照片，Lightroom 只是后台引擎（0.11.0）。

数据来源有两路，按小写规范化后的路径合并：
  1. Lightroom 目录里软件文件夹（含子文件夹）的照片（插件命令 list_folder_photos，分页取全）；
  2. 磁盘扫描软件文件夹（复用 importer.scan_folder 的规则：扩展名白名单、深度、隐藏/系统目录、不跟随链接）。
磁盘上有、目录里没有 -> “尚未加入 Lightroom”；目录里有、磁盘上找不到 -> “文件缺失”。

缩略图：页面只请求可见格；后台线程每批最多 8 张向 Lightroom 取（插件一次回传多张受 20 秒上限限制），存进内存缓存
（最多 500 张且总量 64 MB，最久未用先淘汰），由本机图片服务（preview.PreviewServer，只服务缓存里的图、带随机口令）提供 URL。
照片被调整/撤销/还原后缓存失效并重新取。

选中：页面把想选的照片发给后端，后端带 show_folder=软件文件夹 调 select_photos，以 Lightroom 实际选区为准更新高亮。
所有来自页面的值在这里再校验；页面不能传路径或文件夹，只能传当前图库里已知的照片标识。不对文件夹做周期性轮询。
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import secrets

import importer as imp
from preview import PreviewStore
from settings import browse_folder

MAX_PHOTOS = 2000                 # 图库最多显示的照片数
PAGE = 500                        # 每页向 Lightroom 取的张数（插件上限 500）
THUMB_BATCH = 8                   # 每批缩略图张数上限
THUMB_SIZE = 256
THUMB_VERSION = "t"
MAX_SELECT = 50
MAX_REQUEST_IDS = 200             # 一次缩略图请求最多带的标识数
CACHE_ITEMS = 500
CACHE_BYTES = 64 * 1024 * 1024
DIRTY_DELAY = 1.0                 # 照片被调整后，等这么久（让 Lightroom 更新预览）再重新取缩略图
GROUP_ROOT = "（未分类）"
UID_RE = re.compile(r"^[A-Za-z0-9\-]{1,64}$")

MSG_BROWSE_GONE = "浏览目录暂时无法访问，请检查磁盘，或点“换目录”重新选择。"
MSG_OFFLINE = "Lightroom 未连接，无法显示照片信息"
MSG_TIMEOUT = "Lightroom 没有在时限内回复，可能正忙。请稍后再试。"
MSG_TRUNCATED = f"仅显示前 {MAX_PHOTOS} 张。"
MSG_STALE_PREFIX = "暂时无法更新图库，显示的是上一次读到的内容："
MSG_READONLY ="只读模式已开启，无法加入 Lightroom。请先关闭只读模式（删除只读开关文件）后再试。"
THUMB_ERRORS = {"not_found": "照片在 Lightroom 目录中不存在", "timeout": "读取缩略图超时", "too_large": "缩略图过大（超过 150 KB），无法显示",
                "bad_jpeg": "缩略图数据无效", "no_reply": "Lightroom 没有返回该缩略图", "not_added": "尚未加入 Lightroom，没有缩略图"}
AUTO_RETRY_CODES = ("timeout", "too_large")   # 偶发失败（一批同时渲染的超时；真机上冷启动时偶尔先得到过大的预览，再取就正常）：自动再试一次（只一次），仍失败才显示“读取失败”


def norm_key(path) -> str:
    """路径 -> 小写、统一反斜杠、合并重复分隔符、去掉末尾分隔符。两路数据按它匹配（Windows 路径不分大小写）。"""
    p = str(path or "").replace("/", "\\")
    p = re.sub(r"\\+", r"\\", p)
    if len(p) > 3:
        p = p.rstrip("\\")
    return p.lower()


def err_text(e: Exception) -> str:
    name = type(e).__name__
    if name == "PluginNotConnected":
        return MSG_OFFLINE
    if name == "BridgeTimeout":
        return MSG_TIMEOUT
    return (str(e).strip() or "未知错误")[:200]


def group_of(path: str, base: str, fallback: str = "") -> str:
    """文件所在子文件夹（相对软件文件夹，用 / 连接）；直接在软件文件夹里的归“（未分类）”。"""
    p = str(path).replace("/", "\\")
    b = str(base).replace("/", "\\").rstrip("\\")
    if norm_key(p).startswith(b.lower() + "\\"):
        rel = p[len(b) + 1:]
        d = rel.rpartition("\\")[0]
        return d.replace("\\", "/") if d else GROUP_ROOT
    return fallback or GROUP_ROOT


def order_key(p: dict, sort: str):
    """排序键：name = 文件名（不分大小写）；time = 拍摄时间（没有的排最后），再按文件名。"""
    nm = (p.get("name") or "").lower()
    if sort == "time":
        c = p.get("captured")
        return (c is None or c == "", str(c or ""), nm)
    return (nm,)


def sort_groups(photos: list[dict], sort: str = "name") -> list[dict]:
    """按分类分组：“（未分类）”在最前，其余按名称；组内按 sort 排序。返回 [{"name","count","photos":[...]}]。"""
    groups: dict[str, list] = {}
    for p in photos:
        groups.setdefault(p["group"], []).append(p)
    names = sorted(groups, key=lambda g: (g != GROUP_ROOT, g.lower()))
    return [{"name": g, "count": len(groups[g]), "photos": sorted(groups[g], key=lambda p: order_key(p, sort))} for g in names]


class ThumbStore(PreviewStore):
    """缩略图缓存：键 = (照片标识, 尺寸, 版本)；内存 LRU，条数与总字节数都有上限，超出时先淘汰最久未用的。
    继承 PreviewStore 是为了直接给 preview.PreviewServer 用（它只需要 bytes_of）。"""

    def __init__(self, max_items: int = CACHE_ITEMS, max_bytes: int = CACHE_BYTES):
        super().__init__(max_cache=max_items, max_initial=0)
        self.max_bytes = max_bytes
        self._bytes = 0

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def put(self, photo_id, edge, version, raw, size=None) -> dict:
        key = (photo_id, edge, version)
        with self._lock:
            self._drop(key)
            e = {"id": secrets.token_hex(8), "key": key, "bytes": raw, "size": size, "t": time.time(), "version": version}
            self._by_key[key] = e
            self._by_id[e["id"]] = e
            self._bytes += len(raw)
            self._evict()
            return e

    def peek(self, photo_id, edge=THUMB_SIZE, version=THUMB_VERSION) -> dict | None:
        with self._lock:
            return self._by_key.get((photo_id, edge, version))

    def _drop(self, key) -> None:
        e = self._by_key.get(key)
        if e is not None:
            self._bytes -= len(e["bytes"])
        super()._drop(key)

    def _evict(self) -> None:
        while len(self._by_key) > 1 and (len(self._by_key) > self._max_cache or self._bytes > self.max_bytes):
            self._drop(next(iter(self._by_key)))

    def invalidate(self, photo_id: str) -> int:
        """丢掉这张照片的所有缓存条目；返回丢掉的条数。"""
        with self._lock:
            keys = [k for k in self._by_key if k[0] == photo_id]
            for k in keys:
                self._drop(k)
            return len(keys)


class PhotoLibrary:
    """lr 需要：connected、library_list(path, offset, limit)、library_thumbnails(ids, size)、library_select(ids, active, show_folder)、
    selected_all()、metadata_of(id)、readonly_error()、import_photo(path)。server 提供图片服务（preview.PreviewServer，store 为 ThumbStore）。"""

    def __init__(self, settings, lr, emit, server, *, scan_fn=imp.scan_folder, on_selected=None, busy_fn=lambda: False,
                 add_fn=imp.add_to_lightroom, sleep=time.sleep, dirty_delay: float = DIRTY_DELAY, run_async=None, clock=time.monotonic):
        self.settings, self.lr, self.emit, self.server = settings, lr, emit, server
        self.store: ThumbStore = server.store
        self._scan_fn, self._on_selected, self._busy_fn, self._add_fn, self._sleep = scan_fn, on_selected, busy_fn, add_fn, sleep
        self._dirty_delay, self._clock = dirty_delay, clock
        self._run_async = run_async or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._lock = threading.RLock()
        self._select_lock = threading.Lock()
        # 数据
        self.state_name = "idle"                 # idle | loading | ready | error
        self.message = ""
        self.base = ""
        self.base_exists = False
        self.in_catalog = False
        self.truncated = False
        self.photos: list[dict] = []
        self._by_uid: dict[str, dict] = {}
        self.stale = False                       # 最近一次刷新失败、显示的是上一次的结果
        self._loaded_base = ""                   # self.photos 来自哪个浏览目录
        # 选中
        self.sel_ids: list[str] = []
        self.active: str | None = None
        self._selecting = False
        self._suppress_sig = None
        # 刷新
        self._refreshing = False
        self._again = False
        self.refresh_seconds: float | None = None
        # 缩略图
        self._queue: list[str] = []
        self._inflight: set[str] = set()
        self._wanted: set[str] = set()
        self._failed: dict[str, str] = {}
        self._retried: set[str] = set()
        self._dirty: dict[str, float] = {}
        self._stale_inflight: set[str] = set()
        self.stats = {"requested": 0, "hits": 0, "fetched": 0, "failed": 0, "batches": 0, "batch_max": 0, "fetch_seconds": 0.0, "bytes": 0}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 加入 Lightroom
        self._add: dict | None = None
        self._add_cancel = threading.Event()

    # ================================================================ 刷新
    def refresh(self) -> dict:
        """后台刷新图库（软件启动、导入完成、加入完成、手动刷新时调用；不做周期性轮询）。已在刷新则排一次补刷。"""
        with self._lock:
            if self._refreshing:
                self._again = True
                return {"ok": True, "started": False}
            self._refreshing = True
            self._again = False
            self.state_name = "loading"
        self.emit({"type": "library_changed"})
        self._run_async(self._refresh_loop)
        return {"ok": True, "started": True}

    def _refresh_loop(self) -> None:
        try:
            while True:
                try:
                    self.refresh_sync()
                except Exception as e:           # noqa: BLE001 - 兜底：不让后台线程悄悄死掉
                    self._set_error(err_text(e))
                with self._lock:
                    if not self._again:
                        self._refreshing = False
                        break
                    self._again = False
        finally:
            with self._lock:
                self._refreshing = False
            self.emit({"type": "library_changed"})

    def refresh_sync(self) -> None:
        t0 = time.perf_counter()
        base = browse_folder(self.settings.data)
        exists = os.path.isdir(base)
        with self._lock:
            self.base, self.base_exists = base, exists
        if not exists and self.settings.data.get("gallery_folder"):      # 另选的浏览目录暂时不在（比如移动硬盘没接）：设置保留
            return self._set_error(MSG_BROWSE_GONE)
        if not self.lr.connected:
            return self._set_error(MSG_OFFLINE)
        cat_photos: list[dict] = []
        in_catalog, cat_truncated = False, False
        if exists:
            try:
                in_catalog, cat_photos, cat_truncated = self._fetch_catalog(base)
            except Exception as e:               # noqa: BLE001
                return self._set_error(err_text(e))
        disk: dict[str, tuple[str, int]] = {}
        disk_truncated = False
        if exists:
            scan = self._scan_fn(base, max_files=MAX_PHOTOS + 1)
            if scan.get("error"):
                return self._set_error(scan["error"])
            disk_truncated = bool(scan.get("truncated"))
            for path, size in scan["files"]:
                disk[norm_key(path)] = (path, size)
        self._merge(base, in_catalog, cat_photos, cat_truncated, disk, disk_truncated)
        self.refresh_seconds = round(time.perf_counter() - t0, 3)

    def _fetch_catalog(self, base: str) -> tuple[bool, list[dict], bool]:
        out: list[dict] = []
        offset, total, in_catalog = 0, 0, False
        while offset < MAX_PHOTOS:
            r = self.lr.library_list(base, offset, min(PAGE, MAX_PHOTOS - offset))
            if not r.get("in_catalog"):
                return False, [], False
            in_catalog = True
            total = int(r.get("total") or 0)
            page = [p for p in (r.get("photos") or []) if isinstance(p, dict) and isinstance(p.get("id"), str) and UID_RE.fullmatch(p["id"])]
            out.extend(page)
            if not page or offset + len(r.get("photos") or []) >= total:
                break
            offset += len(r.get("photos") or [])
        return in_catalog, out, total > len(out) and len(out) >= MAX_PHOTOS

    def _merge(self, base, in_catalog, cat_photos, cat_truncated, disk, disk_truncated) -> None:
        recs: list[dict] = []
        cat_keys = set()
        for p in cat_photos:
            path = str(p.get("path") or "")
            key = norm_key(path)
            cat_keys.add(key)
            ext = path.rsplit(".", 1)[-1] if "." in path else ""
            flag = p.get("flag") if p.get("flag") in ("pick", "reject") else "none"
            rating = p.get("rating") if isinstance(p.get("rating"), int) and not isinstance(p.get("rating"), bool) else None
            recs.append({"uid": p["id"], "name": str(p.get("name") or os.path.basename(path) or p["id"]), "path": path, "key": key,
                         "group": group_of(path, base, str(p.get("subfolder") or "")), "format": str(p.get("format") or ext).upper()[:6],
                         "rating": rating, "flag": flag, "captured": p.get("captured") or None, "w": p.get("width"), "h": p.get("height"),
                         "vc": bool(p.get("is_virtual_copy")), "in_catalog": True, "on_disk": key in disk})
        if not cat_truncated:                    # 目录没取全时无法判断“尚未加入”，宁可不标
            for key, (path, size) in disk.items():
                if key in cat_keys:
                    continue
                ext = path.rsplit(".", 1)[-1] if "." in path else ""
                recs.append({"uid": "n-" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16], "name": os.path.basename(path),
                             "path": path, "key": key, "group": group_of(path, base), "format": ext.upper()[:6], "rating": None,
                             "flag": "none", "captured": None, "w": None, "h": None, "vc": False, "in_catalog": False, "on_disk": True})
        truncated = cat_truncated or disk_truncated or len(recs) > MAX_PHOTOS
        recs = [p for g in sort_groups(recs, "name") for p in g["photos"]][:MAX_PHOTOS]
        with self._lock:
            self.photos, self._by_uid = recs, {p["uid"]: p for p in recs}
            self.in_catalog, self.truncated = in_catalog, truncated
            self.state_name, self.message, self.stale = "ready", "", False
            self._loaded_base = base
            # 选区里已不在图库的照片去掉；等待中的缩略图请求同理
            self.sel_ids = [i for i in self.sel_ids if i in self._by_uid]
            if self.active not in self._by_uid:
                self.active = self.sel_ids[-1] if self.sel_ids else None
            self._queue = [i for i in self._queue if i in self._by_uid]
            self._failed = {k: v for k, v in self._failed.items() if k in self._by_uid}

    def _set_error(self, msg: str) -> None:
        """刷新失败。同一个浏览目录上次读到过照片时，保留上一次的列表和选区，只提示“暂时无法更新”（stale=True）；
        从没读到过（或换了目录）才显示错误并清空。"""
        with self._lock:
            if self.photos and norm_key(self._loaded_base) == norm_key(self.base):
                self.state_name, self.message, self.stale = "ready", MSG_STALE_PREFIX + msg, True
                return
            self.state_name, self.message, self.stale = "error", msg, False
            self.photos, self._by_uid, self.truncated = [], {}, False
            self.sel_ids, self.active = [], None

    # ================================================================ 状态
    def public(self, p: dict) -> dict:
        return {"id": p["uid"], "name": p["name"], "group": p["group"], "format": p["format"], "rating": p["rating"], "flag": p["flag"],
                "captured": p["captured"], "w": p["w"], "h": p["h"], "vc": p["vc"], "added": p["in_catalog"],
                "missing": bool(p["in_catalog"] and not p["on_disk"])}

    def state(self) -> dict:
        with self._lock:
            photos = [self.public(p) for p in self.photos]
            thumbs = {}
            for p in self.photos:
                e = self.store.peek(p["uid"])
                if e is not None:
                    thumbs[p["uid"]] = self.server.url_for(e)
            return {"ok": True, "state": self.state_name, "message": self.message, "stale": self.stale,
                    "base": self.base, "base_exists": self.base_exists,
                    "in_catalog": self.in_catalog, "lr_connected": bool(self.lr.connected), "total": len(photos), "limit": MAX_PHOTOS,
                    "truncated": self.truncated, "truncated_message": MSG_TRUNCATED if self.truncated else "",
                    "not_added": sum(1 for p in photos if not p["added"]), "missing": sum(1 for p in photos if p["missing"]),
                    "photos": photos, "thumbs": thumbs, "failed": dict(self._failed),
                    "selection": {"ids": list(self.sel_ids), "active": self.active}, "add": self.add_state(), "max_select": MAX_SELECT}

    # ================================================================ 缩略图
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.3)
            self._wake.clear()
            try:
                while not self._stop.is_set() and self.process_thumbs_once():
                    pass
            except Exception:                    # noqa: BLE001
                pass

    def request_thumbs(self, ids, retry=False) -> dict:
        """页面请求可见格的缩略图。已缓存的立刻返回 URL；其余排队，由后台线程每批 ≤8 张取，结果经 library_thumbs 事件送出。
        只接受当前图库里已知的标识；每次请求会取代上一次尚未开始的排队（页面滚动后不再可见的不用取）。"""
        if not isinstance(ids, (list, tuple)):
            return {"ok": False, "message": "照片列表无效。"}
        if len(ids) > MAX_REQUEST_IDS:
            return {"ok": False, "message": f"一次最多请求 {MAX_REQUEST_IDS} 张缩略图。"}
        want: list[str] = []
        for i in ids:
            if not isinstance(i, str) or not UID_RE.fullmatch(i):
                return {"ok": False, "message": "照片标识无效。"}
            if i not in want:
                want.append(i)
        retry = retry is True
        thumbs, pending, queue = {}, [], []
        with self._lock:
            if any(i not in self._by_uid for i in want):
                return {"ok": False, "message": "包含不在当前图库中的照片，请刷新后重试。"}
            self._wanted = set(want)
            for i in want:
                self.stats["requested"] += 1
                if not self._by_uid[i]["in_catalog"]:
                    thumbs[i] = {"error": THUMB_ERRORS["not_added"]}
                    continue
                e = self.store.get(i, THUMB_SIZE, THUMB_VERSION)
                if e is not None and i not in self._dirty:
                    self.stats["hits"] += 1
                    thumbs[i] = {"url": self.server.url_for(e)}
                    continue
                if retry:
                    self._failed.pop(i, None)
                    self._retried.discard(i)
                if i in self._failed:
                    thumbs[i] = {"error": self._failed[i]}
                    continue
                pending.append(i)
                if i not in self._inflight:
                    queue.append(i)
            self._queue = queue
        self._wake.set()
        return {"ok": True, "thumbs": thumbs, "pending": pending}

    def process_thumbs_once(self) -> bool:
        """取一批（≤8 张）缩略图。返回是否取了。线程里反复调用；测试里可直接调用。"""
        now = self._clock()
        with self._lock:
            for uid, t in list(self._dirty.items()):          # 被调整过的照片：等一会儿再重新取
                if now - t >= self._dirty_delay:
                    del self._dirty[uid]
                    if uid in self._wanted and uid in self._by_uid and uid not in self._queue and uid not in self._inflight:
                        self._queue.insert(0, uid)
            batch = [i for i in self._queue if i in self._by_uid][:THUMB_BATCH]
            self._queue = self._queue[len(batch):] if batch else []
            if not batch:
                return False
            self._inflight.update(batch)
        t0 = time.perf_counter()
        items: list[dict] = []
        got: dict[str, dict] = {}
        batch_error = ""
        try:
            res = self.lr.library_thumbnails(batch, THUMB_SIZE)
            got = {t["id"]: t for t in res.get("thumbnails") or [] if isinstance(t, dict) and t.get("id") in batch}
        except Exception as e:                   # noqa: BLE001
            batch_error = err_text(e)
        dt = time.perf_counter() - t0
        with self._lock:
            self.stats["batches"] += 1
            self.stats["batch_max"] = max(self.stats["batch_max"], len(batch))
            self.stats["fetch_seconds"] = round(self.stats["fetch_seconds"] + dt, 3)
            for uid in batch:
                self._inflight.discard(uid)
                t = got.get(uid)
                if uid in self._stale_inflight:                  # 取的途中照片又被调整：这张作废，稍后重取
                    self._stale_inflight.discard(uid)
                    self._dirty[uid] = self._clock()
                    continue
                if t and t.get("ok") and t.get("jpeg"):
                    e = self.store.put(uid, THUMB_SIZE, THUMB_VERSION, t["jpeg"], (t.get("width"), t.get("height")))
                    self._failed.pop(uid, None)
                    self._retried.discard(uid)
                    self.stats["fetched"] += 1
                    self.stats["bytes"] += len(t["jpeg"])
                    items.append({"id": uid, "url": self.server.url_for(e)})
                else:
                    code = (t or {}).get("error") or ("no_reply" if not batch_error else "")
                    if code in AUTO_RETRY_CODES and uid not in self._retried and uid in self._wanted:
                        self._retried.add(uid)
                        self._queue.append(uid)
                        continue
                    msg = batch_error or THUMB_ERRORS.get(code) or (f"无法读取缩略图（{str(code)[:60]}）")
                    self._failed[uid] = msg
                    self.stats["failed"] += 1
                    items.append({"id": uid, "error": msg})
        if items:
            self.emit({"type": "library_thumbs", "items": items})
        return True

    def invalidate_thumbs(self, photo_ids) -> int:
        """照片被调整/撤销/还原后：丢掉缓存的缩略图，等一会儿后（如果还在可见范围）重新取。返回丢掉的条数。"""
        n = 0
        with self._lock:
            for uid in set(i for i in photo_ids if isinstance(i, str)):
                n += self.store.invalidate(uid)
                self._failed.pop(uid, None)
                if uid in self._inflight:
                    self._stale_inflight.add(uid)
                elif uid in self._by_uid:
                    self._dirty[uid] = self._clock()
        self._wake.set()
        return n

    def cache_hit_rate(self) -> float | None:
        r = self.stats["requested"]
        return round(self.stats["hits"] / r, 3) if r else None

    # ================================================================ 星级与旗标刷新（AI 挑片写入/撤销后）
    def refresh_meta(self, photo_ids) -> None:
        ids = [i for i in dict.fromkeys(photo_ids) if isinstance(i, str)]
        with self._lock:
            ids = [i for i in ids if i in self._by_uid and self._by_uid[i]["in_catalog"]]
        if not ids:
            return
        if len(ids) > 20:
            self.refresh()
            return
        items = []
        for uid in ids:
            try:
                m = (self.lr.metadata_of(uid) or {}).get("metadata") or {}
            except Exception:                    # noqa: BLE001 - 读不到就保持旧值
                continue
            rating = m.get("rating") if isinstance(m.get("rating"), int) and not isinstance(m.get("rating"), bool) else None
            flag = m.get("flag") if m.get("flag") in ("pick", "reject") else "none"
            with self._lock:
                p = self._by_uid.get(uid)
                if p is None:
                    continue
                p["rating"], p["flag"] = rating, flag
            items.append({"id": uid, "rating": rating, "flag": flag})
        if items:
            self.emit({"type": "library_meta", "items": items})

    # ================================================================ 选中
    def _check_ids(self, ids, max_count: int) -> list[str] | str:
        if not isinstance(ids, (list, tuple)):
            return "照片列表无效。"
        if not ids:
            return "请先选择照片。"
        out: list[str] = []
        for i in ids:
            if not isinstance(i, str) or not UID_RE.fullmatch(i):
                return "照片标识无效。"
            if i not in out:
                out.append(i)
        if len(out) > max_count:
            return f"一次最多选择 {max_count} 张。"
        with self._lock:
            for i in out:
                p = self._by_uid.get(i)
                if p is None:
                    return "包含不在当前图库中的照片，请刷新后重试。"
                if not p["in_catalog"]:
                    return "所选照片中有尚未加入 Lightroom 的，请先点击“加入 Lightroom”。"
        return out

    def select(self, ids, active=None) -> dict:
        """把这些照片在 Lightroom 里选中（带 show_folder=软件文件夹），并以 Lightroom 实际选区为准更新高亮。"""
        chk = self._check_ids(ids, MAX_SELECT)
        if isinstance(chk, str):
            return {"ok": False, "status": "refused", "message": chk, "selected": list(self.sel_ids), "active": self.active}
        ids = chk
        if active is not None and (not isinstance(active, str) or active not in ids):
            return {"ok": False, "status": "refused", "message": "当前照片必须是所选照片之一。",
                    "selected": list(self.sel_ids), "active": self.active}
        base = browse_folder(self.settings.data)
        with self._select_lock:
            self._selecting = True
            try:
                try:
                    data = self.lr.library_select(ids, active, base if os.path.isdir(base) else None)
                except Exception as e:           # noqa: BLE001
                    sel = self._read_lr_selection()
                    if sel is not None:
                        self._adopt(sel[0], sel[1])
                    out = {"ok": False, "status": "failed", "message": err_text(e), "selected": list(self.sel_ids), "active": self.active}
                    self._after_select()
                    return out
                status = data.get("status") or ("selected" if data.get("all_selected") else "partial")
                msg = ""
                if status == "uncertain":
                    sel = self._read_lr_selection()
                    ids_now, act = sel if sel is not None else (list(self.sel_ids), self.active)
                    msg = "Lightroom 没有在时限内回复，不确定选中是否生效。已按 Lightroom 当前选区更新显示。"
                else:
                    ids_now = [i for i in (data.get("selected") or []) if isinstance(i, str)]
                    act = active if active in ids_now else None
                    if status != "selected":
                        n = len(data.get("not_selected") or [])
                        why = str(data.get("reason") or "").strip()
                        msg = f"Lightroom 未能选中其中 {n or '部分'} 张照片。" + (why if why else "")
                self._adopt(ids_now, act)
                ok = status == "selected" and set(self.sel_ids) >= set(ids)
            finally:
                self._selecting = False
        self._after_select()
        return {"ok": ok, "status": status, "message": msg, "selected": list(self.sel_ids), "active": self.active,
                "not_selected": [i for i in (data.get("not_selected") or []) if isinstance(i, str)]}

    def _after_select(self) -> None:
        """有选区就立即刷新“当前照片”（预览、本次调整等），不等 3 秒轮询。"""
        if self.sel_ids and self._on_selected:
            try:
                self._on_selected()
            except Exception:                    # noqa: BLE001
                pass

    def _read_lr_selection(self):
        try:
            r = self.lr.selected_all()
        except Exception:                        # noqa: BLE001
            return None
        if r is None:
            return None
        return [p["id"] for p in r.get("photos") or [] if p.get("id")], r.get("active_id")

    def _adopt(self, ids, active) -> None:
        with self._lock:
            ids = [i for i in ids if i in self._by_uid]
            if active not in ids:
                active = ids[-1] if ids else None
            changed = (ids, active) != (self.sel_ids, self.active)
            self.sel_ids, self.active = list(ids), active
            self._suppress_sig = None
        if changed:
            self.emit({"type": "library_selection", "ids": list(ids), "active": active})

    def clear_selection(self) -> dict:
        """清除图库里的选择标记。Lightroom 没有“取消全部选择”的命令，所以 Lightroom 里的选区不变；
        在 Lightroom 的选区改变之前，图库不会再把它重新标出来。"""
        with self._lock:
            self._suppress_sig = self._last_lr_sig
            self.sel_ids, self.active = [], None
        self.emit({"type": "library_selection", "ids": [], "active": None})
        return {"ok": True, "message": "已清除图库中的选择标记。Lightroom 里的选区不变，AI 挑片、导出仍按 Lightroom 当前选区进行。"}

    _last_lr_sig = None

    def on_lr_selection(self, ev: dict) -> None:
        """Lightroom 里的选区变了（约每 3 秒读取一次；软件自己的选中也会触发）。以 Lightroom 为准更新高亮。"""
        photos = [p for p in ev.get("photos") or [] if isinstance(p, dict) and isinstance(p.get("id"), str)]
        ids = [p["id"] for p in photos]
        active = ev.get("active_id")
        count = ev.get("count") if isinstance(ev.get("count"), int) else len(ids)
        sig = (count, active, tuple(ids))
        with self._lock:
            self._last_lr_sig = sig
            if self._selecting:
                return
            if self._suppress_sig is not None:
                if sig == self._suppress_sig:
                    return
                self._suppress_sig = None
            known = [i for i in ids if i in self._by_uid]
            if count > len(ids) and set(known) <= set(self.sel_ids) and active == self.active and count == len(self.sel_ids):
                return                           # 事件只带前 20 张：和我们已知的大选区一致，不动
            if count > len(ids) and not known:
                return
            new_active = active if active in known else (known[-1] if known else None)
            if (known, new_active) == (self.sel_ids, self.active):
                return
            self.sel_ids, self.active = known, new_active
        self.emit({"type": "library_selection", "ids": list(known), "active": new_active})

    # ================================================================ 加入 Lightroom
    def add_state(self) -> dict | None:
        with self._lock:
            return dict(self._add) if self._add else None

    def add_missing(self) -> dict:
        """把“尚未加入”的照片逐张加入 Lightroom 目录（复用导入的 add_to_lightroom：忙时重试、uncertain 不重复添加）。路径只来自后端上一次扫描。"""
        try:
            ro = self.lr.readonly_error()
        except Exception:                        # noqa: BLE001
            ro = None
        if ro:
            return {"ok": False, "message": MSG_READONLY}
        if not self.lr.connected:
            return {"ok": False, "message": MSG_OFFLINE}
        try:
            if self._busy_fn():
                return {"ok": False, "message": "正在导入，请等导入完成后再加入。"}
        except Exception:                        # noqa: BLE001
            pass
        with self._lock:
            if self._add and self._add.get("state") == "running":
                return {"ok": False, "message": "正在加入 Lightroom，请稍候。"}
            todo = [(p["name"], p["path"]) for p in self.photos if not p["in_catalog"] and p["on_disk"]]
            if not todo:
                return {"ok": False, "message": "没有需要加入 Lightroom 的照片。"}
            self._add = {"state": "running", "i": 0, "n": len(todo), "name": "", "counts": {"added": 0, "uncertain": 0, "failed": 0, "pending": 0},
                         "problems": [], "cancelled": False}
            self._add_cancel = threading.Event()
        self.emit({"type": "library_add", **self.add_state()})
        cancel = self._add_cancel
        self._run_async(lambda: self._add_loop(todo, cancel))
        return {"ok": True, "n": len(todo)}

    def _add_loop(self, todo, cancel: threading.Event) -> None:
        try:
            for idx, (name, path) in enumerate(todo):
                if cancel.is_set():
                    with self._lock:
                        self._add["cancelled"] = True
                    break
                with self._lock:
                    self._add.update(i=idx, name=name)
                self.emit({"type": "library_add", **self.add_state()})
                if not os.path.isfile(path):
                    r = {"lr": "failed", "reason": "文件已不存在。"}
                elif not self.lr.connected:
                    r = {"lr": "pending", "reason": "Lightroom 未连接。"}
                else:
                    r = self._add_fn(path, self.lr.import_photo, sleep=self._sleep)
                key = {"imported": "added", "already": "added", "uncertain": "uncertain", "pending": "pending"}.get(r["lr"], "failed")
                with self._lock:
                    self._add["counts"][key] += 1
                    if key != "added":
                        self._add["problems"].append({"name": name, "lr": r["lr"], "reason": r["reason"]})
                    self._add["i"] = idx + 1
                if key == "pending":             # Lightroom 断开：不再逐张尝试
                    break
        finally:
            with self._lock:
                self._add["state"] = "done"
                self._add["name"] = ""
                self._add["problems"] = self._add["problems"][:50]
            self.emit({"type": "library_add", **self.add_state()})
            self.refresh()

    def cancel_add(self) -> dict:
        with self._lock:
            running = bool(self._add and self._add.get("state") == "running")
        if running:
            self._add_cancel.set()
        return {"ok": running}

    def close_add(self) -> dict:
        with self._lock:
            if self._add and self._add.get("state") == "done":
                self._add = None
        return {"ok": True}
