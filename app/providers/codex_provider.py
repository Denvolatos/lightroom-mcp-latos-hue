# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Codex CLI provider: one JSONL process per turn, resumed by thread id."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from frozen import helper_command
from persistent_session import kill_tree
from claude_bridge import (ENABLED_WRITE_TOOLS, MSG_TIMEOUT, READONLY_TOOLS, SYSTEM_PROMPT, TOOL_LABELS, WORKDIR,
                           IdleWatchdog, friendly_error)
from .base import AIProvider, NOT_INSTALLED, NOT_LOGGED_IN, READY, UNKNOWN, make_status

TIMEOUT_SECONDS = 180            # 空闲超时（每个事件重新计时，确认卡片等待中暂停）
TOOLS = READONLY_TOOLS + ENABLED_WRITE_TOOLS
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Codex 对 MCP 工具默认 60 秒超时、启动默认约 10 秒：确认卡片最长等 120 秒，代理每轮还要冷启动服务，都放宽
TOOL_TIMEOUT_SEC = 300
STARTUP_TIMEOUT_SEC = 30
MSG_FAILED = "Codex 运行失败，请检查登录或网络连接。"


def codex_error_text(event: dict) -> str:
    """error / turn.failed 事件里的真实错误信息（两种写法：message 或 error.message）。"""
    err = event.get("error")
    for v in (event.get("message"), err.get("message") if isinstance(err, dict) else err):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def friendly_codex_error(text: str) -> str:
    """把 Codex 的错误翻成中文；登录类单独说 codex login，其余沿用 claude_bridge.friendly_error 的口径。"""
    low = (text or "").lower()
    if not low.strip():
        return MSG_FAILED
    if "not logged in" in low or "login" in low or "unauthorized" in low or "401" in low or "api key" in low:
        return "Codex 命令行尚未登录或登录已失效。请在终端运行 codex login 后重试。"
    if "mcp" in low and ("start" in low or "timed out" in low or "handshak" in low):
        return "Codex 未能启动 Lightroom 工具服务，请重试；仍失败时请在“环境检查”中查看。（" + text.strip()[:120] + "）"
    return friendly_error(text)


def find_codex() -> str | None:
    path = shutil.which("codex")
    if path:
        return path
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    return next((str(p) for p in local.glob("*/codex.exe")), None)


def codex_env(extra: dict | None = None) -> dict[str, str]:
    env = {**os.environ, **(extra or {})}
    env.setdefault("CODEX_HOME", env.get("LRAPP_CODEX_HOME") or str(Path.home() / ".codex"))
    return env


def check_login(path: str, run=subprocess.run) -> bool | None:
    try:
        result = run([path, "login", "status"], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=10,
                     env=codex_env(), creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "logged in" in output.lower():
        return True
    if "not logged" in output.lower():
        return False
    return None


def build_command(path: str, thread_id: str | None, workdir: Path, prompt: str) -> list[str]:
    proxy_command, *proxy_args = helper_command("codex-proxy")
    cmd = [path, "exec", "resume"] if thread_id else [path, "exec"]
    cmd += ["--json", "--ignore-user-config", "--ignore-rules", "--strict-config", "--skip-git-repo-check"]
    for feature in ("shell_tool", "apps", "view_image", "multi_agent", "goals", "hooks",
                    "shell_snapshot", "skill_mcp_dependency_install"):
        cmd += ["--disable", feature]
    cmd += ["-c", 'web_search="disabled"', "-c", 'sandbox_mode="read-only"',
            "-c", f"mcp_servers.lightroom_mcp.command={json.dumps(proxy_command.replace(os.sep, '/'))}",
            "-c", f"mcp_servers.lightroom_mcp.args={json.dumps([a.replace(os.sep, '/') for a in proxy_args])}",
            "-c", 'mcp_servers.lightroom_mcp.env_vars=["LRAPP_PORT", "LRAPP_TOKEN"]',
            "-c", f"mcp_servers.lightroom_mcp.enabled_tools={json.dumps(TOOLS)}",
            "-c", "mcp_servers.lightroom_mcp.required=true",
            "-c", f"mcp_servers.lightroom_mcp.tool_timeout_sec={TOOL_TIMEOUT_SEC}",
            "-c", f"mcp_servers.lightroom_mcp.startup_timeout_sec={STARTUP_TIMEOUT_SEC}"]
    cmd += [thread_id, "-"] if thread_id else ["--sandbox", "read-only",
                                              "-C", str(workdir), "-"]
    return cmd


def _tool_text(result: dict) -> str:
    return "\n".join(str(part.get("text", "")) for part in (result.get("content") or [])
                     if isinstance(part, dict) and part.get("type") == "text")


class CodexProvider(AIProvider):
    id = "codex"
    display_name = "Codex 命令行"
    short_name = "Codex"
    supports_images = True
    experimental = False             # 贡献者已在真机验收（PR #5/#6 的验证报告）；标记机制保留给以后的新来源
    privacy_notice = "使用 Codex 时，选中照片的预览会发送至所选的 Codex 服务。"

    def __init__(self, state_file=None, persistent=True, *, workdir: Path = WORKDIR,
                 find=find_codex, login_check=check_login, clock=time.monotonic):
        self.workdir = Path(workdir)
        self._find, self._login_check, self._clock = find, login_check, clock
        self._cache: tuple[float, dict] | None = None
        self._env: dict = {}
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self.thread_id: str | None = None
        self.alive = True
        self.spawned_at = None

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict:
        now = self._clock()
        if self._cache and now - self._cache[0] < 30:
            return self._cache[1]
        path = self._find()
        if not path:
            st = make_status(False, NOT_INSTALLED, "未安装 Codex 命令行。", "请安装 Codex CLI 后重试。")
        else:
            logged = self._login_check(path)
            if logged is True:
                st = make_status(True, READY, "已安装并已登录。", "")
            elif logged is False:
                st = make_status(False, NOT_LOGGED_IN, "已安装，但尚未登录。", "请在终端运行 codex login。")
            else:
                st = make_status(True, UNKNOWN, "已安装，登录状态无法判断。",
                                 "如发送失败，请在终端运行 codex login status。")
        self._cache = (now, st)
        return st

    def start(self, env: dict | None = None) -> bool:
        self._env = dict(env or {})
        self.alive = True
        return True

    def ensure_running(self) -> bool:
        return self.alive

    def restart(self) -> bool:
        return self.alive

    def send(self, text: str, on_event, **options) -> None:
        path = self._find()
        if not path:
            on_event({"type": "error", "message": "未找到 Codex 命令行，请先安装。"})
            on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        env = codex_env({**self._env, **(options.get("extra_env") or {})})
        prompt = SYSTEM_PROMPT + "\n\n用户：" + text
        cmd = build_command(path, self.thread_id, self.workdir, prompt)
        parts: dict[str, str] = {}
        message: list[str] = []
        tokens, finished, failed, timed_out = 0, False, False, False
        error_text, err_tail = "", []
        try:
            self._proc = subprocess.Popen(cmd, cwd=str(self.workdir), stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                          encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)
        except OSError:
            on_event({"type": "error", "message": "无法启动 Codex 命令行，请检查安装。"})
            on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        proc = self._proc

        def timeout():
            nonlocal timed_out
            timed_out = True
            kill_tree(proc)                          # codex.cmd → node → codex.exe 整棵结束

        watchdog = IdleWatchdog(timeout, idle=TIMEOUT_SECONDS).start()

        def read_stderr():
            try:
                for err_line in proc.stderr:
                    err_tail[:] = (err_tail + [err_line])[-20:]
            except (OSError, ValueError):
                pass

        err_reader = threading.Thread(target=read_stderr, daemon=True)
        err_reader.start()

        def write_prompt():
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (OSError, ValueError):
                pass  # The process may exit or be stopped before reading the prompt.

        threading.Thread(target=write_prompt, daemon=True).start()
        try:
            for line in proc.stdout:
                watchdog.touch()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind, item = event.get("type"), event.get("item") or {}
                if kind == "thread.started":
                    self.thread_id = event.get("thread_id") or self.thread_id
                    on_event({"type": "session", "id": self.thread_id})
                elif kind in ("item.started", "item.updated", "item.completed"):
                    if item.get("type") == "agent_message":
                        ident, full = item.get("id"), item.get("text") or ""
                        old = parts.get(ident, "")
                        delta = full[len(old):] if full.startswith(old) else full
                        parts[ident] = full
                        if delta:
                            message.append(delta)
                            on_event({"type": "text", "text": delta})
                    elif item.get("type") == "mcp_tool_call" and item.get("server") == "lightroom_mcp":
                        tool = item.get("tool", "")
                        if tool not in TOOLS:
                            continue
                        if kind == "item.started":
                            on_event({"type": "tool", "name": tool, "id": item.get("id"),
                                      "input": item.get("arguments") or {},
                                      "label": TOOL_LABELS.get(tool, "正在处理")})
                        elif kind == "item.completed":
                            result = item.get("result") or {}
                            on_event({"type": "tool_result", "id": item.get("id"), "text": _tool_text(result),
                                      "is_error": bool(item.get("error") or result.get("is_error") or
                                                       result.get("isError") or item.get("status") == "failed")})
                elif kind == "turn.completed":
                    usage = event.get("usage") or {}
                    tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
                    finished = True
                elif kind in ("turn.failed", "error"):
                    failed = True
                    error_text = codex_error_text(event) or error_text
            proc.wait()
            err_reader.join(2)
        finally:
            watchdog.cancel()
            kill_tree(proc)                          # 读取中途出错时不留下进程
            self._proc = None
        stopped = self._stop.is_set()
        if stopped:
            on_event({"type": "stopped"})
        elif timed_out:
            on_event({"type": "error", "message": MSG_TIMEOUT})
        elif failed or not finished or proc.returncode != 0:
            on_event({"type": "error", "message": friendly_codex_error(error_text or "".join(err_tail))})
        on_event({"type": "done", "tokens": tokens, "cost": None, "text": "".join(message),
                  "is_error": stopped or timed_out or failed or not finished or proc.returncode != 0})

    def stop(self) -> None:
        self._stop.set()
        kill_tree(self._proc)                        # npm 安装的 codex.cmd 下只 kill 直接子进程停不下来

    def reset(self) -> None:
        self.stop()
        self.thread_id = None

    def close(self) -> None:
        self.stop()
        self.alive = False

    def one_shot(self, fork: bool = False):
        """挑片：新的 Codex 线程（不 resume 聊天线程）。记成经验需要读到对话，codex exec 不能分叉线程，沿用聊天线程（返回 None）。"""
        if fork:
            return None
        other = type(self)(workdir=self.workdir, find=self._find, login_check=self._login_check, clock=self._clock)
        other._env = dict(self._env)
        return other
