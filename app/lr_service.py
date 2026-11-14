# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""窗口进程内直接连接 Lightroom 插件：用于撤销、还原到原始状态、读取当前值、显示连接状态。

做法：在窗口进程里启动一个 server 的 Bridge（插件会同时轮询所有已登记的服务），再用 server 自带的 EditService
执行 restore / restore_original，因此范围检查、改前存盘、还原冲突保护全部沿用 server 的实现，这里不绕过。
"""
from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from pathlib import Path

from ports import clean_stale_announcements, note_port_used, port_order

REPO = Path(__file__).resolve().parent.parent
CONFLICT_MARK = "又发生变化"
log = logging.getLogger("latoshue.lr")

# 读取类调用的超时（秒）。原则：周期性调用（巡检线程每 3 秒读选中照片、预览线程每几秒查一次）用短超时，
# Lightroom 卡住时它们很快放弃、下一轮再试，不会把状态更新拖住几十秒；用户自己点出来、可以等一会儿的操作
# （导出、AI 挑片、保存/套用预设）用长超时，见 patient()。
POLL_READ_TIMEOUT = 10          # list_selected（PR #7 之前是 8）
DEVELOP_READ_TIMEOUT = 20       # get_develop，只有预览线程在用（PR #7 之前是 15）
USER_READ_TIMEOUT = 40          # 用户主动触发的读取（PR #7 把所有读取都放宽到了 40）

REBUILD_BACKOFF_START = 60.0    # 借用模式：重建助手进程后，至少这么久才允许下一次；每次翻倍
REBUILD_BACKOFF_MAX = 600.0
FG_SETTLE_SECONDS = 0.3         # 前台请求结束后，缩略图再等这么久才发下一批

MSG_READ_TIMEOUT ="Lightroom 没有在时限内回应，可能正忙。稍后会自动重试。"
MSG_READ_OFFLINE = "Lightroom 插件未连接。请确认 Lightroom 已打开且插件已启用。"
MSG_READ_FAILED = "Lightroom 没能完成这次读取。请稍后再试；一直不行的话，在 Lightroom 里重新选中这张照片。"
MSG_READONLY_WRITE = "只读模式已开启，不允许修改照片。要修改，请先关闭只读模式。"


def friendly_read_error(e: BaseException) -> str:
    """把读取失败翻成可以直接给用户看的一句话。异常原文可能带本机路径、端口等内部信息，只写进日志，不上界面。"""
    name = type(e).__name__
    if name == "BridgeTimeout":
        return MSG_READ_TIMEOUT
    if name == "PluginNotConnected":
        return MSG_READ_OFFLINE
    return MSG_READ_FAILED


@contextlib.contextmanager
def patient(lr):
    """用户主动触发、可以等的操作：这段代码里 lr 的读取用长超时（USER_READ_TIMEOUT）。
    只对当前线程生效；lr 是测试里的假对象（没有这个开关）时什么也不做。"""
    tl = getattr(lr, "_patience", None)
    if tl is None:
        yield
        return
    old = getattr(tl, "on", False)
    tl.on = True
    try:
        yield
    finally:
        tl.on = old


@contextlib.contextmanager
def foreground(lr):
    """前台请求（选中照片、取中栏预览）：这段时间里缩略图线程先让路，不往插件那条队里塞新的一批（见 wait_foreground_idle）。
    lr 是测试里的假对象（没有这个开关）时什么也不做。"""
    enter = getattr(lr, "_fg_enter", None)
    if enter is None:
        yield
        return
    enter()
    try:
        yield
    finally:
        lr._fg_exit()


def wait_foreground_idle(lr, timeout: float) -> bool:
    """后台请求（缩略图）发下一批之前调用：等前台请求都结束（最多 timeout 秒，防止饿死）。假对象直接返回 True。"""
    wait = getattr(lr, "_fg_wait", None)
    return True if wait is None else wait(timeout)


def version_name_error(name) -> str | None:
    """版本名不合规时返回原因（规则与 server 的 VersionStore 相同：1–40 个字、不含换行等控制字符），合规返回 None。"""
    _import_server()
    from lightroom_mcp import versions
    try:
        versions.clean_name(name)
    except versions.VersionError as e:
        return str(e)
    return None


def valid_edit_id(value) -> bool:
    """修改编号 / 批次编号的格式（形如 20261102-120000-ab12），与 server 的 EditStore 相同。"""
    _import_server()
    from lightroom_mcp import edits
    return isinstance(value, str) and bool(edits.EDIT_ID.match(value))


def _import_server():
    server_dir = str(REPO / "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    from lightroom_mcp import bridge, edits  # noqa: WPS433
    return edits, bridge


def _never_sent(e: BaseException) -> bool:
    """借用通道的请求失败时，能确定“请求根本没送到服务”的情况：连接被拒绝（端口上没有服务），
    或服务直接以 HTTP 错误码拒绝（口令不对、路径不对，命令没有执行）。其余网络错误（连接重置、读超时、回包残缺）
    都可能发生在请求送达之后，一律不算“没连上”。"""
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return True
    reason = getattr(e, "reason", None) if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, ConnectionRefusedError):
        return True
    import socket
    return isinstance(reason, socket.gaierror)


class RemoteBridge:
    """借用常驻 claude 里 lightroom_mcp 服务的插件通道（见 lr_launcher.start_rpc）：接口与 Bridge 的 call/connected 一致。
    这样窗口进程不再单独起一个 Bridge，插件只需轮询一个新服务。"""

    def __init__(self, state_file: Path, token: str, alive=lambda: True, max_age: float = 6.0):
        self.state_file, self.token, self._alive, self.max_age = state_file, token, alive, max_age

    def _state(self) -> dict:
        import json
        try:
            d = json.loads(Path(self.state_file).read_text(encoding="utf-8"))
            if time.time() - float(d.get("t", 0)) <= self.max_age:
                return d
        except (OSError, ValueError, TypeError):
            pass
        return {}

    @property
    def connected(self) -> bool:
        return bool(self._alive() and self._state().get("connected"))

    @property
    def plugin_version(self):
        return self._state().get("plugin_version")

    def call(self, command: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        import json
        import urllib.error
        import urllib.request
        _, bridge_mod = _import_server()
        port = self._state().get("rpc_port")
        if not port or not self._alive():
            raise bridge_mod.PluginNotConnected("助手正在启动或重建连接，请稍后再试。")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/call", method="POST",
            data=json.dumps({"command": command, "params": params or {}, "timeout": timeout}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 10) as r:
                reply = json.loads(r.read().decode("utf-8"))
        except Exception as e:                      # noqa: BLE001 - 按“请求是否可能已送达”分两类
            if _never_sent(e):
                raise bridge_mod.PluginNotConnected("无法连接助手后台，请稍后再试。") from e
            # 请求可能已经送达、插件可能已经执行（比如回包途中助手进程被重启）：状态不确定，让修改记录可以还原
            raise bridge_mod.BridgeTimeout("与助手后台的连接在等待回复时中断，操作结果不确定。") from e
        if reply.get("ok"):
            return reply.get("data", {})
        cls = getattr(bridge_mod, str(reply.get("error_type")), None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, Exception)):
            cls = bridge_mod.BridgeError
        raise cls(reply.get("message", ""))


class LrService:
    def __init__(self, bridge=None, edit_service=None, state_file: Path | None = None, rpc_token: str | None = None,
                 alive=lambda: True, restart_hook=None, library_service=None, lr_running=None, clock=time.monotonic):
        """给了 state_file 与 rpc_token：借用常驻 claude 的服务（RemoteBridge），自己不起 Bridge；否则自己起一个。
        lr_running：() -> bool，Lightroom 进程是否在运行（默认用 lr_autostart.is_running）；借用模式下决定要不要重建助手进程。"""
        self._lr_running = lr_running
        self._clock = clock
        self._inflight = 0                            # 窗口这边正在等回复的命令数（有在途命令时不重建通道）
        self._inflight_lock = threading.Lock()
        self._fg = 0                                  # 进行中的前台请求数（见 foreground()）
        self._fg_last_end = -1e9
        self._fg_cond = threading.Condition()
        self._rebuild_delay = REBUILD_BACKOFF_START   # 借用模式重建助手进程的指数退避
        self._rebuild_next = 0.0
        self._bridge = bridge
        self._edits = edit_service
        self._remote = (state_file, rpc_token, alive) if state_file is not None and rpc_token else None
        self._library_svc = library_service       # 测试时可传入假的图库服务
        self._restart_hook = restart_hook
        self._lock = threading.Lock()
        self._patience = threading.local()            # 见 patient()：当前线程是否在做“用户可以等”的操作
        self.start_error: str | None = None
        self.last_selected_error: str | None = None
        self.started_at: float | None = None          # time.monotonic()，最近一次（重新）启动
        self.restart_count = 0

    # ---- 启动 ------------------------------------------------------
    def start(self) -> bool:
        """启动窗口自己的 Bridge。端口按“最久未使用”优先、先清理失效公告，避免被插件旧轮询任务拖慢发现（见 ports.py）。"""
        with self._lock:
            if self._edits is not None:
                return True
            try:
                if self._remote is not None:
                    edits_mod, _ = _import_server()
                    self._bridge = RemoteBridge(*self._remote)
                    self._edits = edits_mod.EditService(self._call)
                    self.started_at = time.monotonic()
                    return True
                edits_mod, bridge_mod = _import_server()
                clean_stale_announcements()
                b = bridge_mod.Bridge(ports=port_order())
                b.start()
                note_port_used(b.port)
                self._bridge = b
                self._edits = edits_mod.EditService(self._call)
                self.started_at = time.monotonic()
                self.start_error = None
                return True
            except Exception as e:   # 端口占满等
                self.start_error = str(e)
                return False

    def stop(self) -> None:
        if self._bridge is not None and self._remote is None:
            try:
                self._bridge.stop()
            except Exception:
                pass

    def _call(self, command: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        """所有经窗口发给插件的命令都走这里：记下在途数量（restart 据此判断能不能重建通道）。"""
        with self._inflight_lock:
            self._inflight += 1
        try:
            return self._bridge.call(command, params, timeout=timeout)
        finally:
            with self._inflight_lock:
                self._inflight -= 1

    # ---- 前台优先（见模块级 foreground / wait_foreground_idle）--------
    def _fg_enter(self) -> None:
        with self._fg_cond:
            self._fg += 1

    def _fg_exit(self) -> None:
        with self._fg_cond:
            self._fg -= 1
            self._fg_last_end = time.monotonic()
            self._fg_cond.notify_all()

    def _fg_wait(self, timeout: float, settle: float = FG_SETTLE_SECONDS) -> bool:
        """等到没有前台请求、且最近一次结束已过 settle 秒（选中刚结束、预览马上要开始的那一小段空档也让出来）。"""
        end = time.monotonic() + timeout
        with self._fg_cond:
            while True:
                now = time.monotonic()
                gap = settle - (now - self._fg_last_end)
                if self._fg == 0 and gap <= 0:
                    return True
                if now >= end:
                    return False
                self._fg_cond.wait(min(end - now, gap if self._fg == 0 else end - now))

    @property
    def inflight(self) -> int:
        with self._inflight_lock:
            return self._inflight

    def _lightroom_running(self) -> bool:
        try:
            if self._lr_running is not None:
                return bool(self._lr_running())
            import lr_autostart
            return bool(lr_autostart.is_running())
        except Exception:                              # noqa: BLE001 - 查不到按“没在运行”：不去重建
            return False

    def restart(self) -> bool:
        """换一个新端口重新登记（插件约 2 秒内重新发现）。用于长时间连不上时的自动恢复，不需要用户重载插件。
        1.1.1：有在途命令时不重建（插件执行长命令时不发轮询，会被误判断开，重建会丢掉结果）。
        借用模式下重建的是助手进程：只有 Lightroom 确实在运行时才重建（没开 Lightroom 时换端口没有用），并按指数退避。
        返回是否真的重建了。"""
        if self.inflight > 0:
            return False
        if self._remote is not None:                   # 借用模式：重建的是助手进程（换新端口）
            now = self._clock()
            if now < self._rebuild_next or not self._lightroom_running():
                return False
            self._rebuild_next = now + self._rebuild_delay
            self._rebuild_delay = min(self._rebuild_delay * 2, REBUILD_BACKOFF_MAX)
            self.restart_count += 1
            if self._restart_hook:
                self._restart_hook()
            return True
        self.restart_count += 1
        with self._lock:
            self.stop()
            self._bridge = None
            self._edits = None
        return self.start()

    @property
    def plugin_version(self) -> str | None:
        return getattr(self._bridge, "plugin_version", None) if self._bridge is not None else None

    def wait_connected(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.connected:
                return True
            time.sleep(0.2)
        return self.connected

    def _read_timeout(self, short: float) -> float:
        return USER_READ_TIMEOUT if getattr(self._patience, "on", False) else short

    def selected_photo(self) -> dict | None:
        """当前选中（活动）照片：{"id", "name"}；读不到返回 None。"""
        if not self.connected:
            return None
        try:
            r = self._call("list_selected", {"limit": 1}, timeout=self._read_timeout(POLL_READ_TIMEOUT))
        except Exception:
            return None
        pid = r.get("active_id")
        if not pid:
            return {"id": None, "name": None}
        name = next((p.get("name") for p in r.get("photos") or [] if p.get("id") == pid), None)
        return {"id": pid, "name": name}

    def selected_all(self, limit: int = 20) -> dict | None:
        """Lightroom 当前选中的全部照片（只读，一次 list_selected 调用，上限 20 张）：
        {"count", "active_id", "photos": [{"id","name","rating","flag"}]}；读不到返回 None。"""
        if not self.connected:
            return None
        try:
            r = self._call("list_selected", {"limit": max(1, min(int(limit), 20))},
                                  timeout=self._read_timeout(POLL_READ_TIMEOUT))
        except Exception:
            return None
        photos = [{"id": p.get("id"), "name": p.get("name"), "rating": p.get("rating") or 0, "flag": p.get("flag") or "none"}
                  for p in (r.get("photos") or []) if isinstance(p, dict) and p.get("id")]
        count = r.get("count")
        return {"count": count if isinstance(count, int) and not isinstance(count, bool) else len(photos),
                "active_id": r.get("active_id"), "photos": photos}

    def selected_detail(self) -> dict | None:
        """当前选中（活动）照片的 id、文件名与基本信息（相机、ISO、光圈等，取自插件的 list_selected）；读不到返回 None。"""
        if not self.connected:
            return None
        try:
            r = self._call("list_selected", {"limit": 20}, timeout=self._read_timeout(POLL_READ_TIMEOUT))
            self.last_selected_error = None
        except Exception as e:
            log.warning("list_selected failed: %s: %s", type(e).__name__, e)
            self.last_selected_error = friendly_read_error(e)      # 给界面的一句话；原文只进日志
            return None
        pid = r.get("active_id")
        if not pid:
            return {"id": None, "name": None, "info": {}}
        info = next((p for p in r.get("photos") or [] if p.get("id") == pid), {})
        return {"id": pid, "name": info.get("name"), "info": info}

    def develop_of(self, photo_id: str) -> dict:
        """读取一张照片的调整参数（用来判断“编辑版本”是否变化）。出错直接抛异常，由调用方处理。"""
        return self._call("get_develop", {"photo": photo_id}, timeout=self._read_timeout(DEVELOP_READ_TIMEOUT))

    def preview_bytes(self, photo_id: str, long_edge: int) -> tuple[bytes, str | None]:
        """让插件渲染一张预览并读回 JPEG 字节；只接受预览目录内的文件，读完删除（文件名每次唯一，只属于本次请求）。"""
        edits_mod, _ = _import_server()
        from lightroom_mcp import config
        data = self._call("get_preview", {"photo": photo_id, "long_edge": int(long_edge)}, timeout=60)
        path = Path(str(data.get("path", ""))).resolve()
        if config.PREVIEW_DIR.resolve() not in path.parents or not path.is_file():
            raise RuntimeError("插件返回的预览文件不在预期目录，已拒绝读取。")
        raw = path.read_bytes()
        try:
            path.unlink()
        except OSError:
            pass
        return raw, data.get("name")

    @property
    def connected(self) -> bool:
        ok = bool(self._bridge is not None and getattr(self._bridge, "connected", False))
        if ok and self._rebuild_delay != REBUILD_BACKOFF_START:       # 连上了：重建退避回到起点
            self._rebuild_delay, self._rebuild_next = REBUILD_BACKOFF_START, 0.0
        return ok

    # ---- 读取当前值（确认卡片用，尽力而为） -------------------------
    def current_values(self, keys: list[str]) -> dict:
        if not self.connected:
            return {}
        edits_mod, _ = _import_server()
        develop = self._call("get_develop", {"photo": "selected"}, timeout=10)
        out = {}
        for k in keys:
            try:
                out.update(edits_mod.current_values(develop, [k]))
            except Exception:
                pass
        return out

    # ---- 导入 ------------------------------------------------------
    def readonly_error(self) -> str | None:
        """只读开关（文件或环境变量）开着时返回原因，否则 None。判断沿用 server 的 EditService.check_writable。"""
        edits_mod, _ = _import_server()
        svc = self._edits
        if svc is None:
            from lightroom_mcp import config
            svc = edits_mod.EditService(lambda *a, **k: {}, readonly_file=config.READONLY_FILE)
        try:
            svc.check_writable()
        except edits_mod.ReadOnlyError as e:
            return str(e)
        return None

    def import_photo(self, path: str) -> dict:
        """把一个已在本机的照片文件加入 Lightroom 目录（server 的 EditService.import_photo；插件会再校验路径）。
        异常原样抛出，由 importer.add_to_lightroom 翻成中文：PluginNotConnected / ReadOnlyError / BridgeError / BridgeTimeout 等。"""
        if not self.start() or self._edits is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")
        return self._edits.import_photo(path)

    def export_photo(self, folder: str, fmt: str, long_edge: int, quality: int, metadata: str, bit_depth: int,
                     photo: str = "selected") -> dict:
        """导出一张照片（server 的 EditService.export_photo_for_app，只给软件用；不受只读开关拦截）。
        异常原样抛出，由 export_service 翻成中文；超时时服务端返回 status=uncertain。"""
        if not self.start() or self._edits is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")
        return self._edits.export_photo_for_app(folder, fmt, long_edge, quality, metadata, bit_depth, photo)

    # ---- AI 挑片：读目录信息、只写星级与旗标 ------------------------
    def metadata_of(self, photo_id: str) -> dict:
        """一张照片的目录信息（星级、旗标等）；出错直接抛异常。"""
        if not self.start() or self._edits is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")
        return self._edits.get_metadata(photo_id)

    def set_rating_flag(self, photo_id: str, rating: int | None, flag: str | None, reason: str = "") -> dict:
        """只改星级与旗标（server 的 EditService.set_metadata，改前存旧值、可还原；只读开关开着会抛 ReadOnlyError）。
        不传关键词、标题等其他字段。异常原样抛出，由 pick_service 翻成中文。"""
        if not self.start() or self._edits is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")
        return self._edits.set_metadata(rating=rating, flag=flag, reason=reason, photo=photo_id)

    def latest_meta_edit(self, photo_id: str) -> str | None:
        """某张照片最近一条目录信息修改记录的 id（写入状态不确定时用来找到可还原的记录）；找不到返回 None。"""
        svc = self._edits
        try:
            recs = [r for r in svc.store.all() if r.get("kind") == "meta" and r.get("photo_id") == photo_id]
            recs.sort(key=lambda r: r.get("created_ns", 0))
            return recs[-1]["edit_id"] if recs else None
        except Exception:
            return None

    # ---- 图库：列照片、缩略图、选中（server 的 LibraryService，只给软件用，不是 MCP 工具；都不写入照片或目录） ----
    def _library(self):
        if self._library_svc is not None:
            return self._library_svc
        if not self.start() or self._bridge is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")
        _import_server()
        from lightroom_mcp import library as library_mod
        return library_mod.LibraryService(self._call)

    def library_list(self, path: str, offset: int = 0, limit: int = 500) -> dict:
        """软件文件夹（含子文件夹）里、目录已有的照片，分页：{"in_catalog","total","offset","photos":[...]}。"""
        return self._library().list_folder_photos(path, True, offset, limit)

    def library_thumbnails(self, ids: list, size: int = 256) -> dict:
        """一批缩略图（只含 JPEG 字节）：{"size","thumbnails":[{id, ok, jpeg, ...} | {id, ok False, error}]}。"""
        return self._library().get_thumbnails(ids, size)

    def library_select(self, ids: list, active: str | None, show_folder: str | None) -> dict:
        """在 Lightroom 里选中这些照片（不切到前台）：{"status","selected","not_selected","missing","all_selected","reason","message"}。"""
        return self._library().select_photos(ids, active, show_folder)

    # ---- 预设：读取当前照片、套用（只给软件用） --------------------
    def _need_edits(self) -> None:
        if not self.start() or self._edits is None:
            _, bridge_mod = _import_server()
            raise bridge_mod.PluginNotConnected("无法建立与 Lightroom 的连接。")

    def current_photo_settings(self) -> dict | None:
        """当前选中照片的 id、文件名与全部可调参数（插件的 snapshot）：{"id","name","settings","has_local_adjustments"}；读不到返回 None。"""
        sel = self.selected_photo()
        if not sel or not sel.get("id"):
            return None
        try:
            snap = self._call("snapshot", {"photo": sel["id"]}, timeout=60)
        except Exception:
            return None
        return {"id": sel["id"], "name": sel.get("name"), "settings": snap.get("settings") or {},
                "has_local_adjustments": bool(snap.get("has_local_adjustments"))}

    def apply_settings(self, values: dict, reason: str, label: str, photo: str) -> dict:
        """把一组白名单参数作为一次可撤销的修改写入指定照片（server 的 EditService.apply_settings）。异常原样抛出。"""
        self._need_edits()
        return self._edits.apply_settings(values, reason=reason, photo=photo, label=label)

    def apply_lr_preset(self, preset_id: str, reason: str, photo: str) -> dict:
        """套用 Lightroom 预设（EditService.apply_preset：改前存完整快照，带蒙版的被拒绝）。异常原样抛出。"""
        self._need_edits()
        return self._edits.apply_preset(preset_id, reason, photo)

    def list_lr_presets(self, query: str, limit: int) -> dict:
        self._need_edits()
        return self._edits.list_presets(query, limit)

    # ---- 撤销 ------------------------------------------------------
    def _run(self, fn, readonly_msg: str = "只读模式已开启，无法还原。") -> dict:
        """统一把异常翻成 {"ok", "conflict", "message"}（另带 readonly / uncertain 两个标记，供界面区分）。"""
        if not self.start() or self._edits is None:
            return {"ok": False, "conflict": False, "message": "无法建立与 Lightroom 的连接：" + (self.start_error or "")}
        try:
            result = fn(self._edits)
            return {"ok": True, "conflict": False, "result": result, "message": ""}
        except Exception as e:
            msg = str(e)
            name = type(e).__name__
            if name == "PluginNotConnected":
                msg = "Lightroom 插件未连接。请确认 Lightroom 已打开且插件已启用。"
            elif name == "BridgeTimeout":
                msg = "Lightroom 未在规定时间内响应，操作结果待确认。请检查照片当前状态。"
            elif name == "ReadOnlyError":
                msg = readonly_msg
            return {"ok": False, "conflict": CONFLICT_MARK in msg, "readonly": name == "ReadOnlyError",
                    "uncertain": name == "BridgeTimeout", "message": msg}

    def undo(self, edit_id: str, force: bool = False) -> dict:
        return self._run(lambda svc: svc.restore(edit_id, bool(force)))

    def restore_original(self, force: bool = False) -> dict:
        return self._run(lambda svc: svc.restore_original("selected", False, bool(force)))

    # ---- 多版本 / 批量复用（软件界面直接触发；写入都走 server 的 EditService，只读开关、改前存盘、还原保护沿用它的） ----
    def versions(self) -> dict:
        return self._run(lambda svc: svc.list_versions("selected"))

    def version_record(self, name: str) -> dict:
        """当前照片与一个已保存版本的差异（只读）：{"photo_id","name","changed","current","target"}。"""
        def read(svc):
            photo_id, _ = svc.photo_id_of("selected")
            record = svc.versions.get(photo_id, name)
            current = svc.call("snapshot", {"photo": photo_id}, timeout=60).get("settings", {})
            changed = [k for k, v in record.get("settings", {}).items()
                       if k in current and not svc._same(current[k], v)]
            return {"photo_id": photo_id, "name": record["name"], "changed": changed,
                    "current": {k: current[k] for k in changed},
                    "target": {k: record["settings"][k] for k in changed}}
        return self._run(read)

    def version_picture(self, name: str) -> dict:
        def read(svc):
            photo_id, _ = svc.photo_id_of("selected")
            path = svc.versions.thumbnail_path(photo_id, name)
            return {"photo_id": photo_id, "bytes": path.read_bytes() if path else None}
        return self._run(read)

    def save_version(self, name: str, note: str = "") -> dict:
        def save(svc):
            photo_id, _ = svc.photo_id_of("selected")
            try:
                thumbnail, _ = self.preview_bytes(photo_id, 512)
            except Exception as e:                  # noqa: BLE001 - 没有预览图也能保存版本（参数才是版本本身）
                log.warning("version thumbnail failed: %s: %s", type(e).__name__, e)
                thumbnail = None
            return svc.save_version(name, note, photo_id, thumbnail)   # 用上面那张照片的 id，不再读一次“选中”
        return self._run(save)

    def apply_version(self, name: str, photo_id: str, expected_current: dict, expected_target: dict) -> dict:
        """套用一个版本。expected_* 是后端上次给页面看过的差异（由 main.Api 自己保存，不由页面回传）：
        选中的照片、照片当前参数、保存的版本，三者任一与当时不同就拒绝，让用户重新查看。"""
        def apply(svc):
            selected, _ = svc.photo_id_of("selected")
            if selected != photo_id:
                raise ValueError("选中的照片已改变，请重新查看版本。")
            now = svc.call("snapshot", {"photo": selected}, timeout=60).get("settings", {})
            if not isinstance(expected_current, dict) or any(k not in now or not svc._same(now[k], v)
                                                               for k, v in expected_current.items()):
                raise ValueError("照片的调整已改变，请重新查看版本差异。")
            saved = svc.versions.get(selected, name).get("settings", {})
            if not isinstance(expected_target, dict) or any(k not in saved or not svc._same(saved[k], v)
                                                              for k, v in expected_target.items()):
                raise ValueError("保存的版本已改变，请重新查看版本差异。")
            return svc.apply_version(name, photo=selected)
        return self._run(apply, MSG_READONLY_WRITE)

    def batch_plan_from_edit(self, edit_id: str) -> dict:
        return self._run(lambda svc: svc.batch_plan_from_edit(edit_id, "selected"), MSG_READONLY_WRITE)

    def batch_apply(self, plan_id: str) -> dict:
        return self._run(lambda svc: svc.batch_apply(plan_id), MSG_READONLY_WRITE)
