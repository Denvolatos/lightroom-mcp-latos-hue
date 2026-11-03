"""把修图助手接到本机已登录的 Claude Code 命令行（claude -p）。

本模块不依赖界面：负责 ①拼出“干净”的命令 ②解析 stream-json 事件 ③把错误翻成小白能懂的中文。
当前阶段只读：只放行查看类工具，写入类工具一律拒绝。
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

SERVER_NAME = "lightroom_mcp"
REPO = Path(__file__).resolve().parent.parent
WORKDIR = Path.home() / "LrMcp" / "app_workdir"   # 空的中性文件夹，避免读到项目 CLAUDE.md
TIMEOUT_SECONDS = 180

# 只读工具（以 server/lightroom_mcp/tools.py 里 READ_ONLY 标注为准）
READONLY_TOOLS = [
    "lr_status", "lr_list_selected", "lr_get_develop", "lr_get_preview", "lr_review_selected",
    "lr_get_metadata", "lr_list_presets", "lr_plan_from_edit", "lr_list_versions",
    "lr_compare", "lr_list_edits", "lr_doctor",
]
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t}" for t in READONLY_TOOLS]

# 写入/导出/删除类工具：不仅不放行，还直接从模型的工具清单里藏掉（实测让每轮少约 5500 token，也更安全）
WRITE_TOOLS = [
    "lr_set_develop", "lr_set_metadata", "lr_apply_preset", "lr_batch_set_develop", "lr_export",
    "lr_save_version", "lr_apply_version", "lr_delete_version", "lr_restore", "lr_restore_original",
]
DISALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t}" for t in WRITE_TOOLS]

SYSTEM_PROMPT = (
    "你是 Lightroom 修图助手。回复使用正式、克制的书面语气：不闲聊，不使用感叹句、语气词和口语化表达，不使用“你/我”式对话口吻。"
    "每次先调用 lr_status 确认 Lightroom 已连接，再读取照片信息，然后给出方案。"
    "仅在用户明确要求修改时才修改照片，且每次只做小幅调整；调整参数时在 reason 中写明依据。"
    "每项调整后，用简短的陈述句说明：已调整的内容、依据、预期的画面变化。"
    "若调整未被执行（被拒绝、被拦截或失败），如实说明，不重复尝试同一项调整。"
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
    "lr_list_edits": "正在读取调整记录",
    "lr_doctor": "正在检查运行状态",
}


def find_claude() -> str | None:
    """找 claude 命令。Windows 上优先 claude.exe / claude.cmd。"""
    return shutil.which("claude")


def lightroom_server_config() -> dict:
    """lightroom_mcp 服务怎么启动：开发时优先用仓库源码（最新、全部工具），没有源码才用打包好的 lrmcp.exe。"""
    if (REPO / "server" / "lightroom_mcp").exists():
        return {"type": "stdio", "command": sys.executable, "args": ["-m", "lightroom_mcp"],
                "env": {"PYTHONPATH": str(REPO / "server")}}
    exe = REPO / "build" / "dist" / "lrmcp" / "lrmcp.exe"
    return {"type": "stdio", "command": str(exe), "args": []}


def write_mcp_config(directory: Path | None = None) -> Path:
    """写一份只含 lightroom_mcp 的临时配置文件（不含任何密钥）。"""
    directory = directory or Path(tempfile.gettempdir())
    path = directory / "lrmcp_app_mcp.json"
    path.write_text(json.dumps({"mcpServers": {SERVER_NAME: lightroom_server_config()}}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def build_command(prompt: str, mcp_config: Path, session_id: str | None = None,
                  claude_path: str = "claude") -> list[str]:
    cmd = [
        claude_path, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        # 只读本项目的“项目/本地”设置都不要；--setting-sources "" 表示一个来源也不读
        "--setting-sources", "",
        "--disable-slash-commands",
        "--tools", "",
        "--system-prompt", SYSTEM_PROMPT,
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--permission-mode", "dontAsk",
    ]
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
MSG_TIMEOUT = f"等待超过 {TIMEOUT_SECONDS} 秒仍无结果，已停止。请简化请求后重试。"


# ---------------------------------------------------------------- 事件解析
def parse_line(line: str, state: dict | None = None) -> list[dict]:
    """把一行 stream-json 变成 0~n 个界面事件。state 用来记录本轮是否已流式输出过文字。

    事件：{"type":"session","id"} {"type":"text","text"} {"type":"tool","name","label"}
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
                out.append({"type": "tool", "name": name, "label": TOOL_LABELS.get(name, "正在处理")})
            elif block.get("type") == "text" and not state.get("streamed"):
                out.append({"type": "text", "text": block.get("text", "")})
        state["streamed"] = False   # 下一条助手消息重新判断
        if obj.get("error"):
            out.append({"type": "error", "message": friendly_error(str(obj.get("error")))})
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

    def __init__(self, workdir: Path = WORKDIR):
        self.session_id: str | None = None
        self.workdir = workdir
        self._proc: subprocess.Popen | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def reset(self) -> None:
        self.stop()
        self.session_id = None

    def stop(self) -> None:
        self._stopped = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def send(self, prompt: str, emit) -> None:
        claude = find_claude()
        if not claude:
            emit({"type": "error", "message": MSG_NO_CLAUDE})
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        cmd = build_command(prompt, write_mcp_config(), self.session_id, claude)
        self._stopped = False
        state: dict = {}
        stderr_text = ""
        got_done = False
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(self.workdir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            emit({"type": "error", "message": MSG_NO_CLAUDE})
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        proc = self._proc
        timer = threading.Timer(TIMEOUT_SECONDS, self._timeout)
        self._timed_out = False
        timer.start()
        err_chunks: list[str] = []
        threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
        try:
            for line in proc.stdout:
                for ev in parse_line(line, state):
                    if ev["type"] == "session":
                        self.session_id = ev["id"] or self.session_id
                    if ev["type"] == "done":
                        got_done = True
                        self.session_id = ev.get("session_id") or self.session_id
                    emit(ev)
            proc.wait()
        finally:
            timer.cancel()
        stderr_text = "".join(err_chunks)
        if self._timed_out:
            emit({"type": "error", "message": MSG_TIMEOUT})
        elif self._stopped:
            emit({"type": "stopped"})
        elif not got_done:
            emit({"type": "error", "message": friendly_error(stderr_text or "命令行未返回结果")})
        if not got_done:
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})

    def _timeout(self) -> None:
        self._timed_out = True
        self.stop()
