# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""中栏的真实预览：缓存、本机图片服务、取图与刷新调度。

- PreviewStore：内存缓存。键 = (照片 id, 长边, 编辑版本)，编辑版本 = 调整参数的哈希；"初始"图固定保留，不被淘汰。
- PreviewServer：只监听 127.0.0.1 随机端口的微型 HTTP 服务，只能取缓存里的图（路径里要带本次启动的随机口令和缓存条目 id）。
- PreviewManager：后台线程取图。调整/撤销/还原后短防抖刷新，定期轮询选中照片变化；界面不会被阻塞。
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lr_service import foreground, friendly_read_error

log = logging.getLogger("latoshue.preview")

EDGE_MIN, EDGE_MAX, EDGE_DEFAULT = 256, 2048, 1024      # 沿用服务端 config 的限制
DEBOUNCE_SECONDS = 0.6                                    # 连续调整合并为一次刷新
MAX_WAIT_SECONDS = 2.0                                    # 防抖最长推迟时间
MAX_CACHE = 40                                            # 非"初始"图最多保留的数量
MAX_INITIAL = 200                                         # "初始"图最多保留的照片数
POLL_SECONDS = 8.0                                        # 1.1.1：只用来复查 Lightroom 里手动改的参数（换照片由选区轮询立即告知）
HINT_MAX_AGE = 2.5                                        # 选区轮询告知的当前照片在这么久内可直接用，不再读 list_selected
_UNSET = object()
MSG_ERROR = "无法读取预览：请确认 Lightroom 已打开并选中了照片"
MSG_NONE = "Lightroom 中未选中照片"
MSG_LOADING = "正在读取预览"
_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def clamp_edge(n) -> int:
    try:
        return max(EDGE_MIN, min(int(n), EDGE_MAX))
    except (TypeError, ValueError):
        return EDGE_DEFAULT


def develop_version(develop: dict) -> str:
    """调整参数 -> 编辑版本（短哈希）。只看会影响画面的字段，忽略说明文字。"""
    core = {k: develop.get(k) for k in ("settings", "hsl", "has_local_adjustments")}
    raw = json.dumps(core, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def jpeg_size(raw: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            return im.size
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------------------------
class PreviewStore:
    def __init__(self, max_cache: int = MAX_CACHE, max_initial: int = MAX_INITIAL):
        self._lock = threading.Lock()
        self._max_cache, self._max_initial = max_cache, max_initial
        self._by_key: "OrderedDict[tuple, dict]" = OrderedDict()   # key -> entry
        self._by_id: dict[str, dict] = {}
        self._initial: "OrderedDict[str, tuple]" = OrderedDict()   # photo_id -> key（首次看到时的那张）

    def get(self, photo_id: str, edge: int, version: str) -> dict | None:
        with self._lock:
            e = self._by_key.get((photo_id, edge, version))
            if e is not None:
                self._by_key.move_to_end((photo_id, edge, version))
            return e

    def put(self, photo_id: str, edge: int, version: str, raw: bytes, size=None) -> dict:
        key = (photo_id, edge, version)
        with self._lock:
            e = {"id": secrets.token_hex(8), "key": key, "bytes": raw, "size": size, "t": time.time(), "version": version}
            old = self._by_key.pop(key, None)
            if old:
                self._by_id.pop(old["id"], None)
            self._by_key[key] = e
            self._by_id[e["id"]] = e
            self._evict()
            return e

    def _evict(self) -> None:
        pinned = set(self._initial.values())
        while sum(1 for k in self._by_key if k not in pinned) > self._max_cache:
            for k in self._by_key:
                if k not in pinned:
                    self._drop(k)
                    break
        while len(self._initial) > self._max_initial:
            _, k = self._initial.popitem(last=False)
            if k in self._by_key and k not in set(self._initial.values()):
                self._drop(k)

    def _drop(self, key) -> None:
        e = self._by_key.pop(key, None)
        if e:
            self._by_id.pop(e["id"], None)

    def initial(self, photo_id: str) -> dict | None:
        with self._lock:
            k = self._initial.get(photo_id)
            return self._by_key.get(k) if k else None

    def set_initial(self, photo_id: str, entry: dict) -> None:
        with self._lock:
            self._initial[photo_id] = entry["key"]
            self._evict()

    def bytes_of(self, entry_id: str) -> bytes | None:
        with self._lock:
            e = self._by_id.get(entry_id)
            return e["bytes"] if e else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_key)


class PreviewServer:
    """只服务 PreviewStore 里的图：GET /p/<口令>/<16位十六进制条目id>.jpg。口令每次启动随机，其他任何路径、方法、Host 一律拒绝。"""

    def __init__(self, store: PreviewStore):
        self.store = store
        self.token = secrets.token_urlsafe(18)
        self._httpd: ThreadingHTTPServer | None = None
        self.port: int | None = None

    def start(self) -> int:
        store, token = self.store, self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _deny(self, code=404):
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                host = self.headers.get("Host", "")
                parts = self.path.split("?", 1)[0].split("/")       # ['', 'p', token, 'id.jpg']
                if not (host.startswith("127.0.0.1:") or host == "127.0.0.1") or len(parts) != 4 or parts[1] != "p":
                    return self._deny()
                if not hmac.compare_digest(parts[2].encode("utf-8"), token.encode("utf-8")):
                    return self._deny()
                name = parts[3]
                if not name.endswith(".jpg") or not _ID_RE.match(name[:-4]):
                    return self._deny()
                raw = store.bytes_of(name[:-4])
                if raw is None:
                    return self._deny()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)

            do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = lambda self: self._deny(405)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self.port

    def url_for(self, entry: dict) -> str:
        return f"http://127.0.0.1:{self.port}/p/{self.token}/{entry['id']}.jpg"

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None


# ---------------------------------------------------------------------------------------------------------------------
def info_of(detail: dict | None) -> dict:
    """页面信息条用的字段（文件名、相机、ISO、光圈、快门、焦距、格式、原图尺寸）。"""
    i = (detail or {}).get("info") or {}
    size = f"{i['width']} × {i['height']}" if i.get("width") and i.get("height") else None
    return {"name": (detail or {}).get("name") or i.get("name"), "camera": i.get("camera"), "iso": i.get("iso"),
            "aperture": i.get("aperture"), "shutter": i.get("shutter_speed"), "focal": i.get("focal_length"),
            "format": i.get("format"), "size": size}


class PreviewManager:
    """取图与刷新调度。lr 需要：connected、selected_detail()、develop_of(id)、preview_bytes(id, edge)。
    1.1.1：当前照片主要由 show() 告知（Backend 的选区轮询、图库选中），selected_detail() 只在没有新近告知时才用。"""

    def __init__(self, lr, server: PreviewServer, emit, clock=time.monotonic, store: PreviewStore | None = None):
        self.lr, self.server, self.emit, self._clock = lr, server, emit, clock
        self.store = store or server.store
        self.edge = EDGE_DEFAULT
        self.last: dict | None = None            # 最近一次推送给页面的内容（页面刚加载时用来补齐）
        self.fetch_count = 0                     # 实际向 Lightroom 取图的次数（测试与计时用）
        self.last_fetch_seconds: float | None = None
        self._due: float | None = None
        self._first_req: float | None = None
        self._loading_shown = False
        self._lock = threading.Lock()
        self._last_poll = -POLL_SECONDS
        self._hint: dict | None = None           # 最近一次由选区轮询 / 图库选中告知的当前照片（{"id","name","info"?}）
        self._hint_t = float("-inf")
        self._want: object = _UNSET              # 预览应当显示的照片 id（换照片时 +1 代次，旧照片的结果不再推送）
        self._gen = 0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 触发 ------------------------------------------------------
    def request(self, delay: float = DEBOUNCE_SECONDS) -> None:
        """请求刷新。连续请求会合并：延迟请求把时间点往后推（最晚不超过 MAX_WAIT_SECONDS），立即请求（delay=0）把时间点提前。"""
        now = self._clock()
        with self._lock:
            if self._first_req is None:
                self._first_req = now
            due = min(now + delay, self._first_req + MAX_WAIT_SECONDS)
            if self._due is None:
                self._due = due
            elif delay <= 0:
                self._due = min(self._due, due)
            else:
                self._due = max(self._due, due)
        self._wake.set()

    def show(self, detail: dict) -> None:
        """选区轮询（Backend.refresh_photo，约每秒一次）或图库选中告诉预览“当前照片是这张”。
        换了照片：立即开始取预览（不再等下一次轮询，也不再自己读一次选区）；没换：不调 get_develop，
        只在带来了更完整的信息条（相机、ISO 等）时直接更新显示。"""
        if not isinstance(detail, dict):
            return
        pid = detail.get("id")
        with self._lock:
            self._hint, self._hint_t = dict(detail), self._clock()
            changed = pid != self._want
            if changed:
                self._want = pid
                self._gen += 1
        if changed:
            self.request(0)
            return
        cur = self.last or {}
        if pid and "info" in detail and cur.get("state") == "ok" and (cur.get("photo") or {}).get("id") == pid:
            photo = {"id": pid, **info_of(detail)}
            if photo != cur.get("photo"):
                self._publish({**cur, "photo": photo})

    def _fresh_hint(self) -> dict | None:
        with self._lock:
            if self._hint is not None and self._clock() - self._hint_t <= HINT_MAX_AGE:
                return dict(self._hint)
        return None

    def poll(self) -> None:
        """由巡检线程调用：每 POLL_SECONDS 复查一次（Lightroom 里手动改了参数；换照片由 show() 立即处理）。"""
        now = self._clock()
        if now - self._last_poll >= POLL_SECONDS:
            self._last_poll = now
            self.request(0)

    def set_edge(self, edge) -> int:
        self.edge = clamp_edge(edge)
        self.request(0)
        return self.edge

    # ---- 执行 ------------------------------------------------------
    def process_due(self) -> bool:
        """到点就刷新一次（只在后台线程里调用；测试里可直接调用）。返回是否执行了。刷新期间来的新请求会留到下一轮。"""
        with self._lock:
            if self._due is None or self._clock() < self._due:
                return False
            self._due, self._first_req = None, None
        self.refresh()
        return True

    def refresh(self) -> dict:
        """读选中照片 -> 读调整参数得到编辑版本 -> 命中缓存就直接用，否则取一张新预览 -> 推送给页面。"""
        if not self.lr.connected:
            return self._publish({"state": "error", "message": MSG_ERROR})
        detail = self._fresh_hint()              # 选区轮询刚告诉过当前照片：直接用，不再读一次 list_selected
        if detail is None:
            detail = self.lr.selected_detail()
            if detail is None:
                reason = getattr(self.lr, "last_selected_error", None)      # 已经是给用户看的一句话（见 lr_service）
                message = f"无法读取当前照片：{reason}" if reason else MSG_ERROR
                return self._publish({"state": "error", "message": message})
            with self._lock:
                if detail.get("id") != self._want:
                    self._want = detail.get("id")
                    self._gen += 1
        with self._lock:
            gen = self._gen
        pid = detail.get("id")
        if not pid:
            return self._publish({"state": "none", "message": MSG_NONE})
        edge = self.edge
        try:
            with foreground(self.lr):                # 前台请求：缩略图线程先让路
                version = develop_version(self.lr.develop_of(pid))
                entry = self.store.get(pid, edge, version)
                if entry is None:
                    self._loading(pid, detail)
                    t0 = time.monotonic()
                    raw, _ = self.lr.preview_bytes(pid, edge)
                    self.last_fetch_seconds = round(time.monotonic() - t0, 3)
                    self.fetch_count += 1
                    entry = self.store.put(pid, edge, version, raw, jpeg_size(raw))
        except Exception as e:
            # 异常原文（可能带本机路径、端口）只进日志；界面上只给一句分好类的原因
            log.warning("preview refresh failed: %s: %s", type(e).__name__, e)
            if self._superseded(gen):
                return {"state": "superseded"}
            return self._publish({"state": "error", "message": "无法读取预览：" + friendly_read_error(e),
                                  "photo": {"id": pid, **info_of(detail)}})
        if self._superseded(gen):                # 取图期间已经换了照片：这张只进缓存，不推送（避免旧照片盖住新照片）
            return {"state": "superseded"}
        with self._lock:                         # 取图期间轮询带来了更完整的信息条：用新的
            if self._hint is not None and self._hint.get("id") == pid and "info" in self._hint:
                detail = dict(self._hint)
        initial = self.store.initial(pid)
        if initial is None:                      # 软件第一次看到这张照片：这一张就是"初始（首次打开时）"
            self.store.set_initial(pid, entry)
            initial = entry
        return self._publish({"state": "ok", "photo": {"id": pid, **info_of(detail)},
                              "initial": self._img(initial), "current": self._img(entry),
                              "same": initial["id"] == entry["id"], "edge": edge})

    def _superseded(self, gen: int) -> bool:
        with self._lock:
            return self._gen != gen

    def _img(self, e: dict) -> dict:
        w, h = e["size"] if e.get("size") else (None, None)
        return {"url": self.server.url_for(e), "w": w, "h": h, "version": e["version"]}

    def _loading(self, pid: str, detail: dict) -> None:
        cur = self.last or {}
        # 已经显示着同一张照片的图时，保持旧图并只在角落提示"正在读取预览"；否则整块显示加载状态
        if cur.get("state") == "ok" and (cur.get("photo") or {}).get("id") == pid:
            self._loading_shown = True
            self.emit({"type": "preview", **cur, "loading": True})
        elif cur.get("state") == "error":
            return                                   # 上次失败：保持错误提示，后台静默重试，避免每次轮询在“错误/加载”之间闪烁
        else:
            self._publish({"state": "loading", "message": MSG_LOADING, "photo": {"id": pid, **info_of(detail)}})

    def _publish(self, payload: dict) -> dict:
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        shown, self._loading_shown = self._loading_shown, False
        if not shown and self.last is not None and json.dumps(self.last, sort_keys=True, ensure_ascii=False) == key:
            return payload
        self.last = payload
        self.emit({"type": "preview", **payload})
        return payload

    # ---- 线程 ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.15)
            self._wake.clear()
            try:
                self.process_due()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.server.stop()
