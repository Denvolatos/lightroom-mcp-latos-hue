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

from claude_bridge import ENABLED_WRITE_TOOLS, MSG_TIMEOUT, READONLY_TOOLS, SYSTEM_PROMPT, TOOL_LABELS, WORKDIR
from .base import AIProvider, NOT_INSTALLED, NOT_LOGGED_IN, READY, UNKNOWN, make_status

TIMEOUT_SECONDS = 180
TOOLS = READONLY_TOOLS + ENABLED_WRITE_TOOLS
PROXY = Path(__file__).resolve().parent.parent / "codex_proxy.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    cmd = [path, "exec", "resume"] if thread_id else [path, "exec"]
    cmd += ["--json", "--ignore-user-config", "--ignore-rules", "--strict-config", "--skip-git-repo-check"]
    for feature in ("shell_tool", "apps", "view_image", "multi_agent", "goals", "hooks",
                    "shell_snapshot", "skill_mcp_dependency_install"):
        cmd += ["--disable", feature]
    cmd += ["-c", 'web_search="disabled"', "-c", 'sandbox_mode="read-only"',
            "-c", f"mcp_servers.lightroom_mcp.command={json.dumps(sys.executable.replace(os.sep, '/'))}",
            "-c", f"mcp_servers.lightroom_mcp.args={json.dumps([str(PROXY).replace(os.sep, '/')])}",
            "-c", 'mcp_servers.lightroom_mcp.env_vars=["LRAPP_PORT", "LRAPP_TOKEN"]',
            "-c", f"mcp_servers.lightroom_mcp.enabled_tools={json.dumps(TOOLS)}",
            "-c", "mcp_servers.lightroom_mcp.required=true"]
    cmd += [thread_id, "-"] if thread_id else ["--sandbox", "read-only",
                                              "-C", str(workdir), "-"]
    return cmd


def _tool_text(result: dict) -> str:
    return "\n".join(str(part.get("text", "")) for part in (result.get("content") or [])
                     if isinstance(part, dict) and part.get("type") == "text")


class CodexProvider(AIProvider):
    id = "codex"
    display_name = "Codex 命令行"
    supports_images = True
    experimental = True
    experimental_notice = "该来源由外部贡献者接入，尚未在真实 Codex 与 Lightroom 上完成验收，请在测试照片上使用。"
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
        try:
            self._proc = subprocess.Popen(cmd, cwd=str(self.workdir), stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                          encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)
        except OSError:
            on_event({"type": "error", "message": "无法启动 Codex 命令行，请检查安装。"})
            on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        proc = self._proc

        def timeout():
            nonlocal timed_out
            timed_out = True
            if proc.poll() is None:
                proc.kill()

        watchdog = threading.Timer(TIMEOUT_SECONDS, timeout)
        watchdog.start()

        def write_prompt():
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (OSError, ValueError):
                pass  # The process may exit or be stopped before reading the prompt.

        threading.Thread(target=write_prompt, daemon=True).start()
        try:
            for line in proc.stdout:
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
            proc.wait()
        finally:
            watchdog.cancel()
            self._proc = None
        stopped = self._stop.is_set()
        if stopped:
            on_event({"type": "stopped"})
        elif timed_out:
            on_event({"type": "error", "message": MSG_TIMEOUT})
        elif failed or not finished or proc.returncode != 0:
            on_event({"type": "error", "message": "Codex 运行失败，请检查登录或网络连接。"})
        on_event({"type": "done", "tokens": tokens, "cost": None, "text": "".join(message),
                  "is_error": stopped or timed_out or failed or not finished or proc.returncode != 0})

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    def reset(self) -> None:
        self.stop()
        self.thread_id = None

    def close(self) -> None:
        self.stop()
        self.alive = False
