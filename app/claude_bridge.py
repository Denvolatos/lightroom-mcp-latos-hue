# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""把修图助手接到本机已登录的 Claude Code 命令行（claude -p）。

本模块不依赖界面：负责 ①拼出“干净”的命令 ②解析 stream-json 事件 ③把错误翻成小白能懂的中文。
查看类工具直接放行；调整/还原类工具按“逐项确认”开关决定直接放行或逐项确认；其余写入类工具隐藏。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from frozen import helper_command, is_frozen
from timing import TurnTimer

SERVER_NAME = "lightroom_mcp"
REPO = Path(__file__).resolve().parent.parent
WORKDIR = Path.home() / "LrMcp" / "app_workdir"   # 空的中性文件夹，避免读到项目 CLAUDE.md
TIMEOUT_SECONDS = 180          # 空闲超时：这么久没有任何输出才停止（有确认卡片在等用户时暂停计时）
MAX_TURN_SECONDS = 900         # 一轮的总上限（防止无限挂起）

# 只读工具（以 server/lightroom_mcp/tools.py 里 READ_ONLY 标注为准）
READONLY_TOOLS = [
    "lr_status", "lr_list_selected", "lr_get_develop", "lr_get_preview", "lr_review_selected",
    "lr_get_metadata", "lr_list_presets", "lr_plan_from_edit", "lr_list_versions",
    "lr_compare", "lr_list_edits", "lr_doctor",
]
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t}" for t in READONLY_TOOLS]

# 写入/导出/删除类工具（以 server 的标注为准）。本阶段只开放 ENABLED_WRITE_TOOLS，其余直接从模型的工具清单里藏掉
# （实测让每轮少约 5500 token，也更安全）。
WRITE_TOOLS = [
    "lr_set_develop", "lr_set_metadata", "lr_apply_preset", "lr_batch_set_develop", "lr_export",
    "lr_save_version", "lr_apply_version", "lr_delete_version", "lr_restore", "lr_restore_original",
]
ENABLED_WRITE_TOOLS = ["lr_set_develop", "lr_restore", "lr_restore_original"]
BLOCKED_WRITE_TOOLS = [t for t in WRITE_TOOLS if t not in ENABLED_WRITE_TOOLS]
ENABLED_WRITE_FULL = [f"mcp__{SERVER_NAME}__{t}" for t in ENABLED_WRITE_TOOLS]
DISALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t}" for t in BLOCKED_WRITE_TOOLS]

# 逐项确认：由 claude 的 --permission-prompt-tool 把每次写入请求转给这个小服务，再转给窗口
PERM_SERVER_NAME = "lrapp_confirm"
PERM_TOOL = f"mcp__{PERM_SERVER_NAME}__approve"

SYSTEM_PROMPT = (
    "你是 Lightroom 修图助手。回复使用正式、克制的书面语气：不闲聊，不使用感叹句、语气词和口语化表达，不使用“你/我”式对话口吻。"
    "每次先调用 lr_status 确认 Lightroom 已连接，再读取照片信息，然后给出方案。"
    "仅在用户明确要求修改时才修改照片，且每次只做小幅调整；调整参数时在 reason 中写明依据。"
    "每项调整后，用简短的陈述句说明：已调整的内容、依据、预期的画面变化。"
    "若调整未被执行（被拒绝、被拦截或失败），如实说明，不重复尝试同一项调整。"
    "可用的修改工具只有 lr_set_develop、lr_restore、lr_restore_original；套用预设、保存版本、导出、星级旗标和批量修改由用户在软件界面中操作，"
    "用户提出这类需求时说明在软件中的操作位置，不寻找其他工具。"
    "回复保持简短。"
)

# 工具名对应的界面状态文字
TOOL_LABELS = {
    "lr_status": "正在确认 Lightroom 连接状态",
    "lr_list_selected": "正在读取选中的照片",
    "lr_get_develop": "正在读取调整参数",
    "lr_get_preview": "正在读取照片预览",
    "lr_review_selected": "正在逐张读取选中的照片",
    "lr_get_metadata": "正在读取照片信息",
    "lr_list_presets": "正在查询预设",
    "lr_plan_from_edit": "正在整理调整方案",
    "lr_list_versions": "正在读取已保存的版本",
    "lr_compare": "正在对比版本",
    "lr_set_develop": "正在调整参数",
    "lr_restore": "正在还原调整",
    "lr_restore_original": "正在还原到原始状态",
    "lr_list_edits": "正在读取调整记录",
    "lr_doctor": "正在检查运行状态",
}


def find_claude() -> str | None:
    """找 claude 命令。Windows 上优先 claude.exe / claude.cmd。"""
    return shutil.which("claude")


# 让 lightroom_mcp 换用只描述本软件开放工具的说明（见 server/lightroom_mcp/tools.py 的 INSTRUCTIONS_APP）
APP_MODE_ENV = {"LRMCP_APP_MODE": "1"}


def lightroom_server_config(state_file: Path | None = None) -> dict:
    """lightroom_mcp 服务怎么启动：开发时优先用仓库源码（最新、全部工具），没有源码才用打包好的 lrmcp.exe。
    源码方式经 app/lr_launcher.py 启动：端口按“最久未使用”优先，并把“插件是否已连上”写进状态文件（见 lr_launcher.py）。"""
    if is_frozen() or (REPO / "server" / "lightroom_mcp").exists():
        env = {} if is_frozen() else {"PYTHONPATH": str(REPO / "server")}   # 打包后 server 包已在程序里
        env.update(APP_MODE_ENV)
        if state_file is not None:
            env["LRAPP_BRIDGE_STATE"] = str(state_file)
        command, *args = helper_command("lr-launcher")
        return {"type": "stdio", "command": command, "args": args, "env": env}
    exe = REPO / "build" / "dist" / "lrmcp" / "lrmcp.exe"
    return {"type": "stdio", "command": str(exe), "args": [], "env": dict(APP_MODE_ENV)}


def permission_server_config() -> dict:
    """确认服务的启动方式。端口与口令不写进文件，而是用环境变量占位，由窗口进程启动 claude 时传入。"""
    command, *args = helper_command("permission-server")
    return {"type": "stdio", "command": command, "args": args,
            "env": {"LRAPP_PORT": "${LRAPP_PORT}", "LRAPP_TOKEN": "${LRAPP_TOKEN}"}}


def write_mcp_config(directory: Path | None = None, confirm: bool = True, state_file: Path | None = None) -> Path:
    """写一份只含 lightroom_mcp（逐项确认开启时再加确认服务）的临时配置文件（不含任何密钥）。"""
    directory = directory or Path(tempfile.gettempdir())
    path = directory / "lrmcp_app_mcp.json"
    servers = {SERVER_NAME: lightroom_server_config(state_file)}
    if confirm:
        servers[PERM_SERVER_NAME] = permission_server_config()
    path.write_text(json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8")
    return path


def build_command(prompt: str | None, mcp_config: Path, session_id: str | None = None,
                  claude_path: str = "claude", confirm: bool = True, persistent: bool = False) -> list[str]:
    """confirm=True（逐项确认开）：写入类工具不在放行清单里，每次写入由 --permission-prompt-tool 交给窗口确认；
    窗口不可达、超时、被拒绝一律不执行。confirm=False：写入类工具直接放行。
    persistent=True（常驻会话）：不带提示词，改为从标准输入逐行读入 stream-json 消息；此时必须 confirm=True，
    “逐项确认关”由窗口的确认服务自动放行实现（见 confirm_hub.auto_allow），进程参数在整个会话期间不变。"""
    if persistent:
        confirm = True
    allowed = ALLOWED_TOOLS + ([] if confirm else ENABLED_WRITE_FULL)
    cmd = [
        claude_path, "-p", *([prompt] if not persistent else ["--input-format", "stream-json"]),
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        # 只读本项目的“项目/本地”设置都不要；--setting-sources "" 表示一个来源也不读
        "--setting-sources", "",
        "--disable-slash-commands",
        "--tools", "",
        "--system-prompt", SYSTEM_PROMPT,
        "--allowedTools", *allowed,
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]
    if confirm:
        # default 模式下，未放行的工具会触发权限询问，交给确认服务；dontAsk 模式会直接拒绝、不会询问
        cmd += ["--permission-mode", "default", "--permission-prompt-tool", PERM_TOOL]
    else:
        cmd += ["--permission-mode", "dontAsk"]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


# ---------------------------------------------------------------- 错误翻译
def friendly_error(text: str) -> str:
    low = (text or "").lower()
    if "not logged in" in low or "/login" in low or "invalid api key" in low or "authentication" in low:
        return "Claude 命令行尚未登录。请在终端运行 claude，输入 /login 完成登录后重试。"
    if "rate limit" in low or "usage limit" in low or "limit reached" in low or "quota" in low:
        return "订阅额度已用尽，请稍后重试。"
    if "overloaded" in low or "529" in low:
        return "AI 服务繁忙，请稍后重试。"
    if "econnrefused" in low or "network" in low or "enotfound" in low or "timed out" in low:
        return "网络连接异常，请检查网络后重试。"
    return "发生错误：" + (text or "未知错误").strip()[:200]


MSG_NO_CLAUDE = "未找到 claude 命令行。请安装 Claude Code，并在终端运行 claude 完成 /login 登录。"
MSG_TIMEOUT = (f"超过 {TIMEOUT_SECONDS} 秒没有任何进展（或一轮总计超过 {MAX_TURN_SECONDS // 60} 分钟），已停止。"
               "请简化请求后重试。")


class IdleWatchdog:
    """一轮对话的超时：每收到一个事件调用 touch() 重新计时；paused() 为真（有确认卡片在等用户）时暂停计时；
    另有总上限 total。idle / total 不传时在创建时读取 TIMEOUT_SECONDS / MAX_TURN_SECONDS（测试可改）。
    用法：start() 起后台线程，到时调用 on_timeout()；或 wait(event) 阻塞到 event 被设置（True）或超时（False）。"""

    def __init__(self, on_timeout=None, idle: float | None = None, total: float | None = None, paused=None,
                 clock=time.monotonic):
        self.idle = float(TIMEOUT_SECONDS if idle is None else idle)
        self.total = float(MAX_TURN_SECONDS if total is None else total)
        self.on_timeout = on_timeout
        self.paused = paused or _waiting_for_user
        self.clock = clock
        self.started = self.last = clock()
        self.fired = False
        self._cancel = threading.Event()
        self.tick = max(0.02, min(1.0, self.idle / 4))

    def touch(self) -> None:
        self.last = self.clock()

    def expired(self) -> bool:
        now = self.clock()
        try:
            if self.paused():
                self.last = now
        except Exception:
            pass
        return now - self.last > self.idle or now - self.started > self.total

    def wait(self, event: threading.Event) -> bool:
        while not event.wait(self.tick):
            if self.expired():
                self.fired = True
                return False
        return True

    def start(self) -> "IdleWatchdog":
        def loop():
            if not self.wait(self._cancel) and self.on_timeout is not None:
                self.on_timeout()
        threading.Thread(target=loop, daemon=True).start()
        return self

    def cancel(self) -> None:
        self._cancel.set()


def _kill_tree(proc) -> None:
    from persistent_session import kill_tree      # 延迟导入：persistent_session 依赖本模块
    kill_tree(proc)


def _waiting_for_user() -> bool:
    try:
        from confirm_hub import waiting_for_user
    except Exception:
        return False
    return waiting_for_user()


# ---------------------------------------------------------------- 事件解析
def parse_line(line: str, state: dict | None = None) -> list[dict]:
    """把一行 stream-json 变成 0~n 个界面事件。state 用来记录本轮是否已流式输出过文字。

    事件：{"type":"session","id"} {"type":"text","text"} {"type":"tool","name","label","id","input"}
         {"type":"tool_result","id","text","is_error"}
         {"type":"done","tokens","cost","text","is_error"} {"type":"error","message"}
    """
    state = state if state is not None else {}
    line = line.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return []
    t = obj.get("type")
    out: list[dict] = []
    if t == "system" and obj.get("subtype") == "init":
        out.append({"type": "session", "id": obj.get("session_id")})
    elif t == "stream_event":
        ev = obj.get("event", {})
        if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            state["streamed"] = True
            out.append({"type": "text", "text": ev["delta"].get("text", "")})
    elif t == "assistant":
        for block in obj.get("message", {}).get("content", []) or []:
            if block.get("type") == "tool_use":
                name = str(block.get("name", "")).split("__")[-1]
                out.append({"type": "tool", "name": name, "id": block.get("id"), "input": block.get("input") or {},
                            "label": TOOL_LABELS.get(name, "正在处理")})
            elif block.get("type") == "text" and not state.get("streamed"):
                out.append({"type": "text", "text": block.get("text", "")})
        state["streamed"] = False   # 下一条助手消息重新判断
        if obj.get("error"):
            out.append({"type": "error", "message": friendly_error(str(obj.get("error")))})
    elif t == "user":
        content = obj.get("message", {}).get("content", [])
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_result":
                c = block.get("content")
                if isinstance(c, list):
                    c = "".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
                out.append({"type": "tool_result", "id": block.get("tool_use_id"), "text": str(c or ""),
                            "is_error": bool(block.get("is_error"))})
    elif t == "result":
        u = obj.get("usage", {}) or {}
        tokens = sum(int(u.get(k, 0) or 0) for k in
                     ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
        text = obj.get("result") or ""
        if obj.get("is_error"):
            out.append({"type": "error", "message": friendly_error(text)})
        out.append({"type": "done", "tokens": tokens, "cost": obj.get("total_cost_usd"),
                    "text": text, "is_error": bool(obj.get("is_error")), "session_id": obj.get("session_id")})
    return out


# ---------------------------------------------------------------- 运行
class ClaudeSession:
    """一段多轮对话。send() 会阻塞到本轮结束，界面里应放在后台线程调用。"""

    def __init__(self, workdir: Path = WORKDIR, *, fork: bool = False, mcp_dir: Path | None = None):
        """fork=True 且有 session_id 时加 --fork-session：读得到原对话，但结果写进新会话，不改原对话。
        mcp_dir：MCP 配置文件放哪个目录（一次性会话用单独目录，不覆盖常驻会话的配置）。"""
        self.session_id: str | None = None
        self.workdir = workdir
        self.fork = fork
        self.mcp_dir = mcp_dir
        self._proc: subprocess.Popen | None = None
        self._stopped = False
        self._lock = threading.Lock()
        self.last_timing: dict | None = None       # 上一轮的计时摘要（只含时间，见 timing.py）
        self.alive = True                          # 与 PersistentSession 同名的属性，供 Backend 通用使用
        self.spawned_at = None

    @property
    def busy(self) -> bool:
        return bool(self._proc is not None and self._proc.poll() is None)

    def ensure_running(self) -> bool:
        return True

    def restart(self) -> bool:
        return True

    def reset(self) -> None:
        self.stop()
        self.session_id = None

    def stop(self) -> None:
        self._stopped = True
        _kill_tree(self._proc)                     # claude.cmd → node → MCP 服务整棵结束

    def send(self, prompt: str, emit, confirm: bool = True, extra_env: dict | None = None) -> None:
        claude = find_claude()
        if not claude:
            emit({"type": "error", "message": MSG_NO_CLAUDE})
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        timer = TurnTimer("per_turn")
        if self.mcp_dir is not None:
            self.mcp_dir.mkdir(parents=True, exist_ok=True)
        cmd = build_command(prompt, write_mcp_config(self.mcp_dir, confirm=confirm), self.session_id, claude, confirm)
        if self.fork and self.session_id:
            cmd.append("--fork-session")
        self._stopped = False
        state: dict = {}
        stderr_text = ""
        got_done = False
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(self.workdir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env={**os.environ, **(extra_env or {})}, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            emit({"type": "error", "message": MSG_NO_CLAUDE})
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        proc = self._proc
        timer.mark("spawn")
        self._timed_out = False
        watchdog = IdleWatchdog(self._timeout).start()      # 空闲超时：每行输出重新计时
        err_chunks: list[str] = []
        threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
        try:
            for line in proc.stdout:
                watchdog.touch()
                for ev in parse_line(line, state):
                    if ev["type"] == "session":
                        self.session_id = ev["id"] or self.session_id
                    if ev["type"] == "done":
                        got_done = True
                        self.session_id = ev.get("session_id") or self.session_id
                    timer.observe(ev)
                    emit(ev)
            proc.wait()
        finally:
            watchdog.cancel()
            _kill_tree(proc)                       # 读取中途出错时不留下进程
        stderr_text = "".join(err_chunks)
        if self._timed_out:
            emit({"type": "error", "message": MSG_TIMEOUT})
        elif self._stopped:
            emit({"type": "stopped"})
        elif not got_done:
            emit({"type": "error", "message": friendly_error(stderr_text or "命令行未返回结果")})
        if not got_done:
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
        timer.mark("exit")
        self.last_timing = timer.summary()
        timer.write()

    def _timeout(self) -> None:
        self._timed_out = True
        self.stop()
