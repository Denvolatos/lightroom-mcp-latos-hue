# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1 向导：插件项只看窗口通道；AI 那一侧没连上归到 AI 项；旧版服务检查。"""
import wizard as wz

READY_AI = {"name": "Claude Code 命令行", "available": True, "state": "ready", "reason": "已安装并已登录。", "next_step": ""}


def checker(conn, provider=READY_AI, **kw):
    return wz.WizardChecker(lambda: {"base_folder": "C:\\x"}, find_lightroom=lambda c: "C:\\LR\\Lightroom.exe",
                            is_running=lambda: True, get_connection=lambda: conn, get_provider=lambda: provider,
                            isdir=lambda p: True, spawn=lambda fn: fn(), **kw)


def by_id(items):
    return {i["id"]: i for i in items}


def test_plugin_ready_when_window_channel_connected_even_if_ai_side_is_not():
    conn = {"state": "disconnected", "connected": False, "app": True, "side": False, "ai_side": False,
            "plugin_version": "1.1.0"}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.READY and "1.1.0" in items[wz.PLUGIN]["text"]
    ai = items[wz.AI]
    assert ai["state"] == wz.WAIT and "正在连接 Lightroom" in ai["text"] and ai["hint"] == wz.HINT_AI_SIDE


def test_plugin_todo_only_when_window_channel_is_down():
    conn = {"state": "disconnected", "connected": False, "app": False}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.TODO and items[wz.PLUGIN]["hint"] == wz.HINT_PLUGIN


def test_borrowed_channel_down_because_ai_process_gone_is_not_a_plugin_problem():
    conn = {"state": "disconnected", "connected": False, "app": False, "borrowing": True, "claude_alive": False}
    items = by_id(checker(conn).check())
    assert items[wz.PLUGIN]["state"] == wz.WAIT and "AI 助手" in items[wz.PLUGIN]["text"]


def test_ai_ready_when_side_connected_or_not_used():
    for side in (True, None):
        conn = {"state": "connected", "connected": True, "app": True, "ai_side": side}
        assert by_id(checker(conn).check())[wz.AI]["state"] == wz.READY


def test_old_connection_shape_without_app_key_still_works():
    items = by_id(checker({"state": "connected", "connected": True}).check())
    assert items[wz.PLUGIN]["state"] == wz.READY
