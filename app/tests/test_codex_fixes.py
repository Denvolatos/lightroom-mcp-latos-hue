# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Codex 来源的修复（1.1.1）：停止/超时结束整棵进程树；放宽 MCP 工具与启动超时；显示真实错误原因。"""
import sys
import threading
import time
from pathlib import Path

import providers.codex_provider as cp
from providers.codex_provider import CodexProvider

FAKE = str(Path(__file__).with_name("fake_codex.py"))


def provider(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "build_command", lambda path, thread, workdir, prompt: [sys.executable, FAKE])
    return CodexProvider(workdir=tmp_path, find=lambda: "codex", login_check=lambda p: True)


def test_build_command_sets_tool_and_startup_timeouts(tmp_path):
    cmd = cp.build_command("codex", None, tmp_path, "x")
    assert "mcp_servers.lightroom_mcp.tool_timeout_sec=300" in cmd
    assert "mcp_servers.lightroom_mcp.startup_timeout_sec=30" in cmd
    assert cp.TOOL_TIMEOUT_SEC > 125 + 130 - 100          # 大于确认等待（代理 125 秒）


def test_error_text_extraction():
    assert cp.codex_error_text({"type": "error", "message": "boom"}) == "boom"
    assert cp.codex_error_text({"type": "turn.failed", "error": {"message": "quota"}}) == "quota"
    assert cp.codex_error_text({"type": "turn.failed", "error": "plain"}) == "plain"
    assert cp.codex_error_text({"type": "turn.failed"}) == ""


def test_friendly_codex_error():
    assert "额度" in cp.friendly_codex_error("You've hit your usage limit")
    assert "codex login" in cp.friendly_codex_error("401 Unauthorized")
    assert cp.friendly_codex_error("") == cp.MSG_FAILED


def test_real_error_reaches_user(monkeypatch, tmp_path):
    out = []
    provider(monkeypatch, tmp_path).send("quota", out.append)
    errs = [e["message"] for e in out if e["type"] == "error"]
    assert errs == ["订阅额度已用尽，请稍后重试。"] and out[-1]["type"] == "done" and out[-1]["is_error"]


def test_stop_kills_process_tree(monkeypatch, tmp_path):
    killed = []
    real = cp.kill_tree
    monkeypatch.setattr(cp, "kill_tree", lambda proc: killed.append(proc) or real(proc))
    p = provider(monkeypatch, tmp_path)
    out, started = [], threading.Event()

    def on(ev):
        out.append(ev)
        if ev["type"] == "text":
            started.set()
    t = threading.Thread(target=p.send, args=("slow", on))
    t.start()
    assert started.wait(10)
    p.stop()
    t.join(10)
    assert not t.is_alive() and killed and killed[0] is not None
    assert [e["type"] for e in out][-2:] == ["stopped", "done"]


def test_timeout_kills_process_tree(monkeypatch, tmp_path):
    killed = []
    real = cp.kill_tree
    monkeypatch.setattr(cp, "kill_tree", lambda proc: killed.append(proc) or real(proc))
    monkeypatch.setattr(cp, "TIMEOUT_SECONDS", 0.5)
    out = []
    t0 = time.monotonic()
    provider(monkeypatch, tmp_path).send("slow", out.append)
    assert time.monotonic() - t0 < 10 and killed
    assert any(e["type"] == "error" and e["message"] == cp.MSG_TIMEOUT for e in out)
