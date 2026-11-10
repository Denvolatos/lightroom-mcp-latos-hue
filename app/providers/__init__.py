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
            "privacy_notice": cls.privacy_notice, "short_name": cls.short_name or cls.display_name}


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
                    "privacy_notice": "", "short_name": name})
    return out


NOT_CHOSEN = "not_chosen"
MSG_CHOOSE_AI = "请先在“环境检查”里选择要使用的 AI。"


class NotChosenProvider(AIProvider):
    """还没有选择 AI 来源时的占位：不启动任何命令行进程，任何发送都只回一句“请先选择”。
    用户在“环境检查”里点了“使用 Claude / 使用 Codex”之后，才换成真正的来源（见 main.Api.wizard_choose_ai）。
    alive / busy / spawned_at / ensure_running / restart 是后台总管（Backend）会用到的健康检查，这里都是“无事可做”。"""
    id = ""
    display_name = "尚未选择"
    alive = True
    busy = False
    spawned_at = None

    def status(self) -> dict:
        return make_status(False, NOT_CHOSEN, "还没有选择要使用的 AI。", MSG_CHOOSE_AI)

    def start(self, env: dict | None = None) -> bool:
        return True

    def send(self, text: str, on_event, **options) -> None:
        on_event({"type": "error", "message": MSG_CHOOSE_AI})
        on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})

    def stop(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass

    def ensure_running(self) -> bool:
        return True

    def restart(self) -> bool:
        return True


class StatusProbe:
    """只为显示“已安装 / 已登录”而存在的探测器：每个来源留一个实例，沿用各自 status() 的 30 秒缓存。
    只运行各命令行自带的本地登录检测（不调用模型、不启动会话）。"""

    def __init__(self):
        self._claude = ClaudeProvider(session=_NoSession())
        self._codex = CodexProvider()

    def rows(self) -> list[dict]:
        return available_providers(self._claude.status(), self._codex.status())


def is_selectable(provider_id: str) -> bool:
    return provider_id in IMPLEMENTED


def create_provider(provider_id: str, **kwargs) -> AIProvider:
    """按 id 创建来源实例；未知或未实现的 id 回退到默认来源。"""
    cls = IMPLEMENTED.get(provider_id) or IMPLEMENTED[DEFAULT_PROVIDER]
    return cls(**kwargs)
