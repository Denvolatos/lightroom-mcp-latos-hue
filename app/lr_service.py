"""窗口进程内直接连接 Lightroom 插件：用于撤销、还原到原始状态、读取当前值、显示连接状态。

做法：在窗口进程里启动一个 server 的 Bridge（插件会同时轮询所有已登记的服务），再用 server 自带的 EditService
执行 restore / restore_original，因此范围检查、改前存盘、还原冲突保护全部沿用 server 的实现，这里不绕过。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from ports import clean_stale_announcements, note_port_used, port_order

REPO = Path(__file__).resolve().parent.parent
CONFLICT_MARK = "又发生变化"


def _import_server():
    server_dir = str(REPO / "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    from lightroom_mcp import bridge, edits  # noqa: WPS433
    return edits, bridge


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
        except (urllib.error.URLError, OSError, ValueError):
            raise bridge_mod.PluginNotConnected("无法连接助手后台，请稍后再试。")
        if reply.get("ok"):
            return reply.get("data", {})
        cls = getattr(bridge_mod, str(reply.get("error_type")), None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, Exception)):
            cls = bridge_mod.BridgeError
        raise cls(reply.get("message", ""))


class LrService:
    def __init__(self, bridge=None, edit_service=None, state_file: Path | None = None, rpc_token: str | None = None,
                 alive=lambda: True, restart_hook=None):
        """给了 state_file 与 rpc_token：借用常驻 claude 的服务（RemoteBridge），自己不起 Bridge；否则自己起一个。"""
        self._bridge = bridge
        self._edits = edit_service
        self._remote = (state_file, rpc_token, alive) if state_file is not None and rpc_token else None
        self._restart_hook = restart_hook
        self._lock = threading.Lock()
        self.start_error: str | None = None
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
                    self._edits = edits_mod.EditService(self._bridge.call)
                    self.started_at = time.monotonic()
                    return True
                edits_mod, bridge_mod = _import_server()
                clean_stale_announcements()
                b = bridge_mod.Bridge(ports=port_order())
                b.start()
                note_port_used(b.port)
                self._bridge = b
                self._edits = edits_mod.EditService(b.call)
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

    def restart(self) -> bool:
        """换一个新端口重新登记（插件约 2 秒内重新发现）。用于长时间连不上时的自动恢复，不需要用户重载插件。"""
        self.restart_count += 1
        if self._remote is not None:                   # 借用模式：重建的是助手进程（换新端口）
            if self._restart_hook:
                self._restart_hook()
            return True
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

    def selected_photo(self) -> dict | None:
        """当前选中（活动）照片：{"id", "name"}；读不到返回 None。"""
        if not self.connected:
            return None
        try:
            r = self._bridge.call("list_selected", {"limit": 1}, timeout=8)
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
            r = self._bridge.call("list_selected", {"limit": max(1, min(int(limit), 20))}, timeout=8)
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
            r = self._bridge.call("list_selected", {"limit": 20}, timeout=8)
        except Exception:
            return None
        pid = r.get("active_id")
        if not pid:
            return {"id": None, "name": None, "info": {}}
        info = next((p for p in r.get("photos") or [] if p.get("id") == pid), {})
        return {"id": pid, "name": info.get("name"), "info": info}

    def develop_of(self, photo_id: str) -> dict:
        """读取一张照片的调整参数（用来判断“编辑版本”是否变化）。出错直接抛异常，由调用方处理。"""
        return self._bridge.call("get_develop", {"photo": photo_id}, timeout=15)

    def preview_bytes(self, photo_id: str, long_edge: int) -> tuple[bytes, str | None]:
        """让插件渲染一张预览并读回 JPEG 字节；只接受预览目录内的文件，读完删除（文件名每次唯一，只属于本次请求）。"""
        edits_mod, _ = _import_server()
        from lightroom_mcp import config
        data = self._bridge.call("get_preview", {"photo": photo_id, "long_edge": int(long_edge)}, timeout=60)
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
        return bool(self._bridge is not None and getattr(self._bridge, "connected", False))

    # ---- 读取当前值（确认卡片用，尽力而为） -------------------------
    def current_values(self, keys: list[str]) -> dict:
        if not self.connected:
            return {}
        edits_mod, _ = _import_server()
        develop = self._bridge.call("get_develop", {"photo": "selected"}, timeout=10)
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
            snap = self._bridge.call("snapshot", {"photo": sel["id"]}, timeout=60)
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
    def _run(self, fn) -> dict:
        """统一把异常翻成 {"ok", "conflict", "message"}。"""
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
                msg = "只读模式已开启，无法还原。"
            return {"ok": False, "conflict": CONFLICT_MARK in msg, "message": msg}

    def undo(self, edit_id: str, force: bool = False) -> dict:
        return self._run(lambda svc: svc.restore(edit_id, bool(force)))

    def restore_original(self, force: bool = False) -> dict:
        return self._run(lambda svc: svc.restore_original("selected", False, bool(force)))
