# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Claude Code 命令行来源：对现有会话类的薄封装，不重写已验证的逻辑。

常驻会话（默认）= persistent_session.PersistentSession；每轮新启动（排查用，LRAPP_PER_TURN=1）= claude_bridge.ClaudeSession。
"""
from __future__ import annotations

import json
import subprocess
import time

import claude_bridge as cb
from persistent_session import PersistentSession

from .base import AIProvider, NOT_INSTALLED, NOT_LOGGED_IN, READY, UNKNOWN, make_status

AUTH_TIMEOUT = 10
AUTH_CACHE_SECONDS = 30


def check_login(claude_path: str, run=subprocess.run) -> bool | None:
    """用 `claude auth status --json`（本地检测，不调用模型）判断是否已登录；无法判断返回 None。
    只取 loggedIn 一个字段，不读取、不保存、不显示任何账号信息。"""
    try:
        r = run([claude_path, "auth", "status", "--json"], capture_output=True, text=True, timeout=AUTH_TIMEOUT,
                encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        v = json.loads(r.stdout).get("loggedIn")
        return v if isinstance(v, bool) else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


class ClaudeProvider(AIProvider):
    id = "claude"
    display_name = "Claude Code 命令行"
    supports_images = True

    def __init__(self, session=None, state_file=None, persistent: bool = True, *, find=None, login_check=None,
                 clock=time.monotonic):
        self.persistent = persistent
        self.session = session if session is not None else (
            PersistentSession(state_file=state_file) if persistent else cb.ClaudeSession())
        self._find = find or cb.find_claude
        self._login_check = login_check or check_login
        self._clock = clock
        self._cache: tuple[float, dict] | None = None

    # ---- 状态 ------------------------------------------------------
    def status(self) -> dict:
        now = self._clock()
        if self._cache and now - self._cache[0] < AUTH_CACHE_SECONDS:
            return self._cache[1]
        path = self._find()
        if not path:
            st = make_status(False, NOT_INSTALLED, "未安装 Claude Code 命令行。",
                             "请安装 Claude Code，并在终端运行 claude，输入 /login 完成登录。")
        else:
            ok = self._login_check(path)
            if ok is True:
                st = make_status(True, READY, "已安装并已登录。", "")
            elif ok is False:
                st = make_status(False, NOT_LOGGED_IN, "已安装，但尚未登录。", "请在终端运行 claude，输入 /login 完成登录。")
            else:
                st = make_status(True, UNKNOWN, "已安装，登录状态无法判断。",
                                 "如发送消息时提示未登录，请在终端运行 claude 并输入 /login。")
        self._cache = (now, st)
        return st

    # ---- 会话（直接转给现有实现）-----------------------------------
    def start(self, env: dict | None = None) -> bool:
        return bool(self.session.start(env)) if self.persistent else True

    def send(self, text: str, on_event, **options) -> None:
        if self.persistent:
            self.session.send(text, on_event)
        else:
            self.session.send(text, on_event, confirm=options.get("confirm", True), extra_env=options.get("extra_env"))

    def stop(self) -> None:
        self.session.stop()

    def reset(self) -> None:
        self.session.reset()

    def close(self) -> None:
        if self.persistent:
            self.session.shutdown()

    # ---- 供后台总管（Backend）使用的健康检查，原样转给会话 ----------
    @property
    def alive(self) -> bool:
        return bool(self.session.alive)

    @property
    def busy(self) -> bool:
        return bool(self.session.busy)

    @property
    def spawned_at(self):
        return self.session.spawned_at

    def ensure_running(self) -> bool:
        return self.session.ensure_running()

    def restart(self) -> bool:
        return self.session.restart()
