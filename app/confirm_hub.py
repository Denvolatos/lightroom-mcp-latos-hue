# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""逐项确认：窗口进程内的小型本机 HTTP 服务 + 待确认队列。

permission_server（由 claude 启动）把写入请求 POST 到这里；界面弹出确认卡片，用户点击后 answer() 放行或拒绝。
安全措施：只监听 127.0.0.1 随机端口；每轮对话生成一次性口令，轮结束即作废；超时（默认 120 秒）视为拒绝。
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from names import param_name

TIMEOUT_SECONDS = 120
MSG_DENIED = "用户在界面中拒绝了该项调整，未执行。"
MSG_TIMEOUT = f"确认超过 {TIMEOUT_SECONDS} 秒未响应，已视为拒绝，未执行。"
MSG_CANCELLED = "本轮已被停止，该项调整未执行。"
MSG_PICK_READONLY = "AI 挑片期间只能查看照片，不允许任何修改，该操作未执行。"
AUTO_TOOLS = ("lr_set_develop", "lr_restore", "lr_restore_original")   # “逐项确认”关闭时自动放行的工具


# 有确认卡片在等用户时，AI 一轮的“空闲超时”暂停计时（见 claude_bridge.IdleWatchdog）。进程内所有 ConfirmHub 共用。
_waiting = 0
_waiting_lock = threading.Lock()


def waiting_for_user() -> bool:
    """当前是否有确认卡片在等用户点击。"""
    return _waiting > 0


def _num(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return format(float(v), ".4g")
    if isinstance(v, list):
        return "曲线(" + str(len(v) // 2) + " 点)"
    return str(v)


def describe_request(tool_name: str, tool_input: dict, current: dict | None = None) -> dict:
    """把一次写入请求整理成确认卡片内容。current: {参数名: 当前值}（取不到可为空）。"""
    name = tool_name.split("__")[-1]
    current = current or {}
    if name == "lr_set_develop":
        items = []
        for key, to in (tool_input.get("changes") or {}).items():
            items.append({"key": key, "label": param_name(key),
                          "from": _num(current[key]) if key in current else "—", "to": _num(to)})
        return {"kind": "set", "title": "拟调整", "items": items, "reason": str(tool_input.get("reason") or "")}
    if name == "lr_restore":
        force = bool(tool_input.get("force"))
        return {"kind": "restore", "title": "拟还原", "items": [],
                "reason": f"还原调整记录 {tool_input.get('edit_id', '')}" + ("（强制覆盖后续改动）" if force else "")}
    if name == "lr_restore_original":
        force = bool(tool_input.get("force"))
        return {"kind": "restore_original", "title": "拟还原到原始状态", "items": [],
                "reason": "将照片还原到首次调整之前" + ("（强制覆盖后续改动）" if force else "")}
    return {"kind": "other", "title": "拟执行：" + name, "items": [], "reason": ""}


class ConfirmHub:
    def __init__(self, emit, timeout: float = TIMEOUT_SECONDS, current_values=None):
        self.emit = emit
        self.timeout = timeout
        self.current_values = current_values      # callable(keys) -> dict，可为 None
        self.port = 0
        self.auto_allow = False                   # True（逐项确认关）：上述工具不弹卡片，直接放行
        self.deny_all = False                     # True（AI 挑片期间）：一切需要确认的工具直接拒绝，不放行也不弹卡片
        self._token: str | None = None
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    # ---- 生命周期 --------------------------------------------------
    def start(self) -> int:
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401
                pass

            def do_POST(self):
                tok = self._token_ok()
                if not tok or self.path != "/ask":
                    return self._reply(401 if not tok else 404, {"allow": False, "message": "未授权。"})
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                except ValueError:
                    return self._reply(400, {"allow": False, "message": "请求无法解析。"})
                self._reply(200, hub.request(body.get("tool_name", ""), body.get("input") or {},
                                             body.get("tool_use_id", "")))

            def _token_ok(self) -> bool:
                if hub._token is None:
                    return False
                got = self.headers.get("Authorization", "").encode("utf-8")
                return hmac.compare_digest(got, f"Bearer {hub._token}".encode("utf-8"))

            def _reply(self, status, obj):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self.port

    def stop(self) -> None:
        self.end_turn()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def begin_turn(self) -> str:
        """每轮对话换一个一次性口令。"""
        self._token = secrets.token_urlsafe(24)
        return self._token

    def end_turn(self) -> None:
        self._token = None
        self.cancel_all(MSG_CANCELLED)

    def begin_session(self) -> str:
        """常驻会话：口令在整个会话期间有效（随进程重建而更换），每轮结束只清理未应答的确认。"""
        return self.begin_turn()

    def finish_turn(self) -> None:
        self.cancel_all(MSG_CANCELLED)

    # ---- 请求与应答 ------------------------------------------------
    def request(self, tool_name: str, tool_input: dict, tool_use_id: str = "") -> dict:
        """阻塞到用户应答、超时或被取消。返回 {"allow", "message"}。"""
        if self.deny_all:
            return {"allow": False, "message": MSG_PICK_READONLY}
        if self.auto_allow and tool_name.split("__")[-1] in AUTO_TOOLS:
            return {"allow": True, "message": ""}
        cur = {}
        if self.current_values and tool_name.split("__")[-1] == "lr_set_develop":
            try:
                cur = self.current_values(list((tool_input.get("changes") or {}).keys())) or {}
            except Exception:
                cur = {}
        cid = secrets.token_hex(6)
        slot = {"event": threading.Event(), "allow": False, "message": MSG_TIMEOUT, "tool_use_id": tool_use_id}
        with self._lock:
            self._pending[cid] = slot
        card = describe_request(tool_name, tool_input, cur)
        global _waiting
        with _waiting_lock:
            _waiting += 1
        try:
            self.emit({"type": "confirm", "id": cid, "tool_use_id": tool_use_id, "timeout": self.timeout, **card})
            slot["event"].wait(self.timeout)
        finally:
            with _waiting_lock:
                _waiting -= 1
        with self._lock:
            self._pending.pop(cid, None)
        self.emit({"type": "confirm_done", "id": cid, "allow": slot["allow"], "message": slot["message"]})
        return {"allow": slot["allow"], "message": slot["message"]}

    def answer(self, cid: str, allow: bool) -> bool:
        with self._lock:
            slot = self._pending.get(cid)
        if not slot:
            return False
        slot["allow"] = bool(allow)
        slot["message"] = "" if allow else MSG_DENIED
        slot["event"].set()
        return True

    def cancel_all(self, message: str = MSG_CANCELLED) -> None:
        with self._lock:
            slots = list(self._pending.values())
        for s in slots:
            s["allow"], s["message"] = False, message
            s["event"].set()
