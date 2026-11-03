"""Lightroom 连接状态的判定（纯函数，便于测试）。

数据来源有两处，都来自软件自己的检测，不是界面猜的：
1. 窗口进程自己的 Bridge：插件最近 25 秒内是否来轮询过（LrService.connected）；
2. 常驻 claude 启动的 lightroom_mcp 服务：由 lr_launcher.py 每秒写的状态文件（它那条通道插件是否真的连上了）。
两者都通才算“已连接”，因为 AI 调用走的是第 2 条，撤销/读取当前值走的是第 1 条。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CONNECTED, CONNECTING, DISCONNECTED = "connected", "connecting", "disconnected"
GRACE_SECONDS = 25            # 刚启动或刚断开后，在这段时间内显示“正在连接”而不是“未连接”
STATE_MAX_AGE = 6             # 状态文件超过这么多秒没更新，视为对应服务已不在

TEXT = {CONNECTED: "Lightroom 已连接", CONNECTING: "Lightroom 正在连接", DISCONNECTED: "Lightroom 未连接"}
HINT_PLUGIN = "请确认 Lightroom 已打开，且已启用 LrMCP 插件（文件 > 增效工具管理器）。无需重启软件，打开后会自动连接。"
HINT_SIDE = "正在重新建立与助手的连接，请稍候。"
HINT_WAIT = "正在连接 Lightroom，请稍候。"
HINT_OK = "插件已连接。"


def read_side_state(path: Path | None, now: float | None = None, max_age: float = STATE_MAX_AGE) -> dict | None:
    """读 lr_launcher 写的状态文件。路径为 None 表示不使用这条检测；文件缺失或过期返回 {"connected": False, "stale": True}。"""
    if path is None:
        return None
    now = time.time() if now is None else now
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if now - float(data.get("t", 0)) <= max_age and data.get("alive", True):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"connected": False, "stale": True}


def evaluate(app_connected: bool, side: dict | None, down_for: float, grace: float = GRACE_SECONDS) -> dict:
    """down_for：已持续多少秒没有处于“已连接”（从未连接过则从启动算起）。"""
    side_ok = True if side is None else bool(side.get("connected"))
    if app_connected and side_ok:
        state, hint = CONNECTED, HINT_OK
    else:
        state = CONNECTING if down_for < grace else DISCONNECTED
        if app_connected:
            hint = HINT_SIDE
        else:
            hint = HINT_WAIT if state == CONNECTING else HINT_PLUGIN
    return {"state": state, "text": TEXT[state], "hint": hint, "connected": state == CONNECTED,
            "app": bool(app_connected), "side": None if side is None else side_ok}
