"""AI 来源注册表。当前真实可用：claude；codex、api 为占位条目（不可选）。"""
from __future__ import annotations

from .base import AIProvider, EVENT_FIELDS, UNAVAILABLE, make_status, validate_event  # noqa: F401
from .claude_provider import ClaudeProvider
from .codex_stub import CodexProvider  # noqa: F401

DEFAULT_PROVIDER = "claude"

# 占位条目：只有名称与说明，无实现
PLACEHOLDERS = {
    "codex": ("Codex 命令行", "Codex 命令行——后续提供，欢迎贡献。"),
    "api": ("API 密钥", "API 密钥（兼容 OpenAI 接口的各家，含 DeepSeek 等）——后续提供。"),
}

# 已实现的来源：id -> 类
IMPLEMENTED = {"claude": ClaudeProvider}


class _NoSession:
    """仅用于检测状态时的空会话（不启动任何进程）。"""
    alive = False
    busy = False
    spawned_at = None


def available_providers(claude_status: dict | None = None) -> list[dict]:
    """返回 [{"id","name","available","state","reason","next_step","selectable"}]。
    claude_status：已有的 Claude 状态（传入当前实例 status() 的结果可避免重复检测）。"""
    st = claude_status if claude_status is not None else ClaudeProvider(session=_NoSession()).status()
    out = [{"id": "claude", "name": ClaudeProvider.display_name, "available": st["available"], "state": st["state"],
            "reason": st["reason"], "next_step": st["next_step"], "selectable": True}]
    for pid, (name, why) in PLACEHOLDERS.items():
        out.append({"id": pid, "name": name, "available": False, "state": UNAVAILABLE, "reason": why,
                    "next_step": "", "selectable": False})
    return out


def is_selectable(provider_id: str) -> bool:
    return provider_id in IMPLEMENTED


def create_provider(provider_id: str, **kwargs) -> AIProvider:
    """按 id 创建来源实例；未知或未实现的 id 回退到默认来源。"""
    cls = IMPLEMENTED.get(provider_id) or IMPLEMENTED[DEFAULT_PROVIDER]
    return cls(**kwargs)
