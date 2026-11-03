"""窗口进程内直接连接 Lightroom 插件：用于撤销、还原到原始状态、读取当前值、显示连接状态。

做法：在窗口进程里启动一个 server 的 Bridge（插件会同时轮询所有已登记的服务），再用 server 自带的 EditService
执行 restore / restore_original，因此范围检查、改前存盘、还原冲突保护全部沿用 server 的实现，这里不绕过。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFLICT_MARK = "又发生变化"


def _import_server():
    server_dir = str(REPO / "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    from lightroom_mcp import bridge, edits  # noqa: WPS433
    return edits, bridge


class LrService:
    def __init__(self, bridge=None, edit_service=None):
        self._bridge = bridge
        self._edits = edit_service
        self._lock = threading.Lock()
        self.start_error: str | None = None

    # ---- 启动 ------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            if self._edits is not None:
                return True
            try:
                edits_mod, bridge_mod = _import_server()
                b = bridge_mod.Bridge()
                b.start()
                self._bridge = b
                self._edits = edits_mod.EditService(b.call)
                return True
            except Exception as e:   # 端口占满等
                self.start_error = str(e)
                return False

    def stop(self) -> None:
        if self._bridge is not None:
            try:
                self._bridge.stop()
            except Exception:
                pass

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
