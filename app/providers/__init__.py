# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 来源注册表。"""
from __future__ import annotations

from .base import AIProvider, EVENT_FIELDS, UNAVAILABLE, make_status, validate_event  # noqa: F401
from .claude_provider import ClaudeProvider
from .codex_provider import CodexProvider

DEFAULT_PROVIDER = "claude"

# 占位条目：只有名称与说明，无实现
PLACEHOLDERS = {
    "api": ("API 密钥", "API 密钥（兼容 OpenAI 接口的各家，含 DeepSeek 等）——后续提供。"),
}

# 已实现的来源：id -> 类
IMPLEMENTED = {"claude": ClaudeProvider, "codex": CodexProvider}


class _NoSession:
    """仅用于检测状态时的空会话（不启动任何进程）。"""
    alive = False
    busy = False
    spawned_at = None


def _flags(cls) -> dict:
    """来源的固定属性：是否实验性及对应的正式提示、数据去向说明。"""
    return {"experimental": bool(cls.experimental), "experimental_notice": cls.experimental_notice,
            "privacy_notice": cls.privacy_notice}


def available_providers(claude_status: dict | None = None, codex_status: dict | None = None) -> list[dict]:
    """返回 [{"id","name","available","state","reason","next_step","selectable"}]。
    claude_status：已有的 Claude 状态（传入当前实例 status() 的结果可避免重复检测）。"""
    st = claude_status if claude_status is not None else ClaudeProvider(session=_NoSession()).status()
    out = [{"id": "claude", "name": ClaudeProvider.display_name, "available": st["available"], "state": st["state"],
            "reason": st["reason"], "next_step": st["next_step"], "selectable": True, **_flags(ClaudeProvider)}]
    codex = codex_status if codex_status is not None else CodexProvider().status()
    out.append({"id": "codex", "name": CodexProvider.display_name, **codex, "selectable": True, **_flags(CodexProvider)})
    for pid, (name, why) in PLACEHOLDERS.items():
        out.append({"id": pid, "name": name, "available": False, "state": UNAVAILABLE, "reason": why,
                    "next_step": "", "selectable": False, "experimental": False, "experimental_notice": "",
                    "privacy_notice": ""})
    return out


def is_selectable(provider_id: str) -> bool:
    return provider_id in IMPLEMENTED


def create_provider(provider_id: str, **kwargs) -> AIProvider:
    """按 id 创建来源实例；未知或未实现的 id 回退到默认来源。"""
    cls = IMPLEMENTED.get(provider_id) or IMPLEMENTED[DEFAULT_PROVIDER]
    return cls(**kwargs)
