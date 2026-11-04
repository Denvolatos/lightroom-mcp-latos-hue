# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""``lrmcp register`` / ``lrmcp unregister``: add or remove this server in Claude Code and Codex.

Uses their own command line tools (``claude mcp ...``, ``codex mcp ...``), so we never edit their config files by
hand. Claude Desktop is not automated in v1.0 (its config file location depends on how it was installed).
"""
from __future__ import annotations

import shutil
import subprocess
import sys

NAME = "lightroom_mcp"  # snake_case: Codex silently ignores other styles in some versions


def server_command() -> list[str]:
    """The command a client should run to start this server."""
    if getattr(sys, "frozen", False):  # PyInstaller build: lrmcp.exe
        return [sys.executable]
    return [sys.executable, "-m", "lightroom_mcp"]


def _run(args: list[str], dry_run: bool) -> tuple[bool, str]:
    shown = " ".join(f'"{a}"' if " " in a else a for a in args)
    if dry_run:
        return True, f"（演练，未执行）{shown}"
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{shown} → 失败：{e}"
    ok = done.returncode == 0
    tail = (done.stdout.strip() or done.stderr.strip())[-200:]
    return ok, f"{shown} → {'成功' if ok else '失败'}{('：' + tail) if tail and not ok else ''}"


def register(dry_run: bool = False) -> list[str]:
    cmd = server_command()
    lines: list[str] = []
    claude, codex = shutil.which("claude"), shutil.which("codex")
    if claude:
        _run([claude, "mcp", "remove", NAME, "--scope", "user"], dry_run)  # make it repeatable; failure is fine
        ok, msg = _run([claude, "mcp", "add", "--transport", "stdio", "--scope", "user", NAME, "--", *cmd], dry_run)
        lines.append(f"{'✅' if ok else '❌'} Claude Code：{msg}")
    else:
        lines.append("➖ 没有找到 claude 命令（没装 Claude Code？），已跳过。")
    if codex:
        _run([codex, "mcp", "remove", NAME], dry_run)
        ok, msg = _run([codex, "mcp", "add", NAME, "--", *cmd], dry_run)
        lines.append(f"{'✅' if ok else '❌'} Codex：{msg}")
    else:
        lines.append("➖ 没有找到 codex 命令（没装 Codex？），已跳过。")
    lines.append(
        "ℹ️ Claude 桌面版暂不自动登记：在 设置 → 开发者 → 编辑配置 里，把下面的命令加到 mcpServers 的 "
        f'"{NAME}" 下（command 填第一项，args 填其余）：{cmd}'
    )
    return lines


def unregister(dry_run: bool = False) -> list[str]:
    lines: list[str] = []
    claude, codex = shutil.which("claude"), shutil.which("codex")
    if claude:
        ok, msg = _run([claude, "mcp", "remove", NAME, "--scope", "user"], dry_run)
        lines.append(f"{'✅' if ok else '❌'} Claude Code：{msg}")
    if codex:
        ok, msg = _run([codex, "mcp", "remove", NAME], dry_run)
        lines.append(f"{'✅' if ok else '❌'} Codex：{msg}")
    return lines or ["没有找到 claude 或 codex 命令，无需处理。"]
