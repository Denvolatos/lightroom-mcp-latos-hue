# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件检查更新（0.15.0）：只检查，用户点了才去浏览器看；绝不自动下载、安装或替换文件。

- 只做一次匿名 GET：api.github.com 上本仓库的 releases 列表（限制响应大小、超时 8 秒）；不带令牌、不带任何用户数据；
- **标签约定**：本仓库的 releases 有两条版本线——Lightroom 插件/服务端（LrMCP）用 `v0.14.0` 这样的标签，
  软件曾用独立前缀 `hue-v`（如 `hue-v1.0.0`）。1.0.1 起软件与 LrMCP 统一版本、统一发布，标签用 `v1.0.1` 这样的 `v` 前缀。
  这里认 `hue-v` 与 `v` 开头、非草稿、非预发布的 release，按 x.y.z 数字取最大者（历史的 `v0.x.0` 数字更小，不会被当成更新）；其他格式一律忽略；
- 结果缓存 24 小时在 ~/LrMcp/app_update_check.json（服务端自己的是 update_check.json，互不覆盖）；
- 任何失败（断网、限流、格式异常、响应过大）都静默：后台检查失败不留痕迹，手动检查只显示“暂时无法检查”；
- “查看新版本”只用系统浏览器打开**自己缓存的** release 网页；地址必须是本仓库 releases 下的 https://github.com 链接，
  页面不能传地址（接口不收参数）；
- HTTP、时钟、打开浏览器、起线程全部可注入，测试里不联网、不开浏览器。
"""
from __future__ import annotations

import json
import re
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

REPO = "Denvolatos/lightroom-mcp-latos-hue"   # 查询用的现名（1.0.1 起）
# 发布页地址同时认现名和旧名：仓库改名后 GitHub 会跳转，API 返回新名，用户手里也可能还有旧链接；旧名永久保留
ACCEPTED_REPOS = (REPO, "Denvolatos/lightroom-mcp-win")
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
TAG_PREFIXES = ("hue-v", "v")              # 1.0.1 起统一发布用 v 前缀；hue-v 是 1.0.0 的历史标签
TAG_PREFIX = TAG_PREFIXES[0]
CACHE_FILE = Path.home() / "LrMcp" / "app_update_check.json"
CHECK_EVERY_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 8.0
MAX_BYTES = 1_000_000                      # 响应超过这么大就当格式异常拒绝
_VERSION = re.compile(rf"^(?:{'|'.join(re.escape(x) for x in TAG_PREFIXES)})?(\d{{1,4}})\.(\d{{1,5}})\.(\d{{1,5}})$")
_PAGE_PREFIXES = tuple(f"/{r}/releases/" for r in ACCEPTED_REPOS)

IDLE, CHECKING, LATEST, AVAILABLE, UNAVAILABLE = "idle", "checking", "latest", "available", "unavailable"
MSG_CHECKING = "检查中…"
MSG_LATEST = "已是最新版本"
MSG_UNAVAILABLE = "暂时无法检查（可能没联网）"


def parse_version(text) -> tuple[int, int, int] | None:
    """`hue-v1.2.3` 或 `1.2.3` -> (1, 2, 3)；其他写法（含插件的 `v0.14.0`、带后缀的、非字符串）一律 None，从不抛异常。"""
    if not isinstance(text, str):
        return None
    m = _VERSION.match(text.strip())
    return tuple(int(x) for x in m.groups()) if m else None   # type: ignore[return-value]


def release_version(tag) -> tuple[int, int, int] | None:
    """release 标签 -> 版本号。认 `v`（1.0.1 起统一）与 `hue-v`（历史）前缀，其他一律 None。"""
    if not isinstance(tag, str) or not tag.strip().startswith(TAG_PREFIXES):
        return None
    return parse_version(tag)


def valid_release_url(url) -> bool:
    """只接受本仓库（现名或旧名）releases 下的 https://github.com 网页链接（拒绝其他域名、其他协议、带账号/端口、含 .. 或控制字符的）。"""
    if not isinstance(url, str) or not url or len(url) > 300 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        return False
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or u.netloc != "github.com" or u.username or u.password or port is not None:
        return False
    prefix = next((p for p in _PAGE_PREFIXES if u.path.startswith(p)), None)
    if prefix is None or len(u.path) == len(prefix) or ".." in u.path.split("/"):
        return False
    return True


def pick_latest(releases) -> dict | None:
    """从 GitHub 返回的 release 列表里挑软件的最新正式版：{"latest": "1.2.3", "url": html_url}；没有则 None。
    跳过草稿、预发布、非 hue-v 标签、版本号不规范的、html_url 不合规的条目；列表本身不是 list 则抛 ValueError。"""
    if not isinstance(releases, list):
        raise ValueError("releases 不是列表")
    best, best_v = None, None
    for r in releases:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        v = release_version(r.get("tag_name"))
        url = r.get("html_url")
        if v is None or not valid_release_url(url):
            continue
        if best_v is None or v > best_v:
            best_v, best = v, {"latest": ".".join(map(str, v)), "url": url}
    return best


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def http_get(url: str, timeout: float = TIMEOUT_SECONDS, max_bytes: int = MAX_BYTES, *, version: str = "") -> bytes:
    """默认的联网函数：匿名 GET，不带令牌/Cookie；响应超过 max_bytes 就报错。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"LatosHue/{version or 'app'}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定的 https 地址
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("响应过大")
    return data


_default_http_get = http_get


class AppUpdateChecker:
    """检查更新的状态与缓存。state() 只读内存/缓存、从不联网；联网只发生在后台线程里。

    current        当前软件版本（settings.APP_VERSION）
    enabled        () -> bool，设置里的 check_updates
    http_get       (url) -> bytes，可注入
    open_url       (url) -> 任意，可注入（默认 webbrowser.open）
    spawn          (fn) -> 起后台线程，可注入
    """

    def __init__(self, current: str, enabled=lambda: True, *, http_get=None, open_url=None, spawn=None,
                 clock=time.time, cache_file: Path | None = None):
        self.current = current
        self._enabled = enabled
        self._get = http_get or (lambda url: _default_http_get(url, version=current))
        self._open = open_url or webbrowser.open
        self._spawn = spawn or self._spawn_thread
        self._clock = clock
        self.cache_file = Path(cache_file) if cache_file is not None else CACHE_FILE
        self._lock = threading.Lock()
        self._state = IDLE
        self._latest = ""
        self._url = ""
        self._message = ""
        self._loaded = False
        self._checking = False

    @staticmethod
    def _spawn_thread(fn) -> None:
        threading.Thread(target=fn, name="app-update-check", daemon=True).start()

    # ---- 缓存 ------------------------------------------------------
    def _read_cache(self) -> dict | None:
        """读缓存并重新校验每个字段；坏文件/坏内容一律当没有缓存。"""
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        at = data.get("checked_at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            return None
        latest, url = data.get("latest", ""), data.get("url", "")
        if latest:
            if parse_version(latest) is None or not valid_release_url(url):
                return None
        else:
            latest, url = "", ""
        return {"checked_at": float(at), "latest": latest, "url": url}

    def _write_cache(self, latest: str, url: str) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps({"checked_at": self._clock(), "latest": latest, "url": url}),
                                       encoding="utf-8")
        except OSError:
            pass                                        # 写不进去不影响本次结果

    def _apply(self, latest: str, url: str) -> None:
        """把“最新版/没有”套进当前状态（调用时已持锁）。"""
        if latest and is_newer(latest, self.current):
            self._state, self._latest, self._url, self._message = AVAILABLE, latest, url, f"有新版本 {latest}"
        else:
            self._state, self._latest, self._url, self._message = LATEST, latest, "", MSG_LATEST

    def _load_cache_locked(self) -> dict | None:
        c = self._read_cache()
        if c is not None and self._state == IDLE:
            self._apply(c["latest"], c["url"])
        self._loaded = True
        return c

    def _ensure_loaded_locked(self) -> None:
        """第一次需要时读缓存。设置里关了自动检查就不读（关了就不该出现“有新版本”的提示）。"""
        if not self._loaded and self._safe_enabled():
            self._load_cache_locked()

    # ---- 对外 ------------------------------------------------------
    def state(self) -> dict:
        """当前状态（不联网）。state：idle（还不知道/已关闭）/ checking / latest / available / unavailable。"""
        with self._lock:
            self._ensure_loaded_locked()
            return {"state": self._state, "current": self.current, "latest": self._latest if self._state == AVAILABLE else "",
                    "message": self._message, "enabled": self._safe_enabled()}

    def _safe_enabled(self) -> bool:
        try:
            return self._enabled() is True
        except Exception:                               # noqa: BLE001
            return False

    def start_background(self) -> None:
        """软件启动时调用：设置关闭则什么都不做；缓存不到 24 小时就直接用缓存；否则在后台查一次。从不阻塞、从不抛异常。"""
        try:
            if not self._safe_enabled():
                return
            with self._lock:
                c = self._load_cache_locked()
                if c is not None and 0 <= self._clock() - c["checked_at"] < CHECK_EVERY_SECONDS:
                    return
                if self._checking:
                    return
                self._checking = True
            self._start(manual=False)
        except Exception:                               # noqa: BLE001
            with self._lock:
                self._checking = False

    def check_now(self) -> dict:
        """手动检查：忽略缓存，立刻返回“检查中”，结果稍后由 state() 取到。这是用户主动点的，所以设置里关了自动检查也照做。"""
        with self._lock:
            if not self._checking:
                self._checking = True
                self._state, self._message = CHECKING, MSG_CHECKING
                start = True
            else:
                start = False
            self._loaded = True
        if start:
            self._start(manual=True)
        return self.state()

    def _start(self, manual: bool) -> None:
        try:
            self._spawn(lambda: self._run(manual))
        except Exception:                               # noqa: BLE001 - 起不了线程就当没检查
            with self._lock:
                self._checking = False
                if manual:
                    self._state, self._message = UNAVAILABLE, MSG_UNAVAILABLE

    def _run(self, manual: bool) -> None:
        result = None
        ok = False
        try:
            result = pick_latest(json.loads(self._get(RELEASES_URL)))
            ok = True
        except Exception:                               # noqa: BLE001 - 断网/限流/格式异常/过大：静默
            ok = False
        with self._lock:
            self._checking = False
            if ok:
                self._apply(result["latest"] if result else "", result["url"] if result else "")
                latest, url = (result["latest"], result["url"]) if result else ("", "")
            elif manual:
                self._state, self._latest, self._url, self._message = UNAVAILABLE, "", "", MSG_UNAVAILABLE
        if ok:
            self._write_cache(latest, url)

    def open_page(self) -> dict:
        """用系统浏览器打开缓存的新版本页面。不收任何地址；没有新版本或地址不合规就不打开。"""
        with self._lock:
            self._ensure_loaded_locked()
            url = self._url if self._state == AVAILABLE else ""
        if not valid_release_url(url):
            return {"ok": False, "message": "目前没有可查看的新版本。"}
        try:
            self._open(url)
        except Exception:                               # noqa: BLE001
            return {"ok": False, "message": "没能打开浏览器。"}
        return {"ok": True, "message": ""}
