"""AI 来源的统一接口。

软件的界面、确认卡片、"本次调整"表格、预览刷新都只认下面定义的"事件"，不关心背后是哪家 AI。
新增一个来源 = 实现 AIProvider 并在 providers/__init__.py 注册。详见 docs/AI来源接口.md。

事件格式（dict，字段以现有 Claude 实现实际产生的为准）：
  {"type": "session",     "id": str}                       会话标识（可选；用于"续接对话"）
  {"type": "text",        "text": str}                     回复文字的增量片段（按到达顺序拼接）
  {"type": "tool",        "name": str, "id": str, "input": dict, "label": str}
                                                           调用了某个 Lightroom 工具（name 不含服务前缀，label 为界面小字）
  {"type": "tool_result", "id": str, "text": str, "is_error": bool}
                                                           工具返回（id 对应 tool 事件的 id；text 为工具的原文返回）
  {"type": "error",       "message": str}                  中文错误提示（见 friendly_error 的口径）
  {"type": "stopped"}                                      本轮被用户中断（之后仍会收到 done）
  {"type": "done",        "tokens": int, "cost": float|None, "text": str, "is_error": bool}
                                                           本轮结束；每次 send() 有且仅有一个 done，且一定是最后一个事件
软件自己产生、来源不需要发的事件：confirm / confirm_done（确认卡片）、status、photo、adjust、preview、connecting。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

EventCallback = Callable[[dict], None]

# 事件类型 -> 必须具备的字段
EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "session": ("id",),
    "text": ("text",),
    "tool": ("name", "id", "input", "label"),
    "tool_result": ("id", "text", "is_error"),
    "error": ("message",),
    "stopped": (),
    "done": ("tokens", "cost", "text", "is_error"),
}

# 状态取值
READY, NOT_INSTALLED, NOT_LOGGED_IN, UNAVAILABLE, UNKNOWN = (
    "ready", "not_installed", "not_logged_in", "unavailable", "unknown")


def make_status(available: bool, state: str, reason: str, next_step: str = "") -> dict:
    """status() 的统一返回：{"available": bool, "state": str, "reason": 中文原因, "next_step": 中文下一步提示}。"""
    return {"available": bool(available), "state": state, "reason": reason, "next_step": next_step}


def validate_event(ev: dict) -> list[str]:
    """检查一个事件是否符合上面的格式，返回问题列表（空表示合格）。契约测试与贡献者自测共用。"""
    t = ev.get("type") if isinstance(ev, dict) else None
    if t not in EVENT_FIELDS:
        return [f"未知事件类型：{t!r}"]
    return [f"{t} 事件缺少字段 {f}" for f in EVENT_FIELDS[t] if f not in ev]


class AIProvider(ABC):
    """一个 AI 来源。send() 阻塞到本轮结束，界面里应放在后台线程调用；on_event 可能在其他线程被调用。"""

    id: str = ""                    # 稳定的英文标识，用于设置文件与注册表
    display_name: str = ""          # 界面显示名（中文）
    supports_images: bool = False   # 能否看图（lr_get_preview 返回的预览图）
    experimental: bool = False      # 实验性来源：设置里会标注，并显示 experimental_notice
    experimental_notice: str = ""   # 实验性来源的正式提示（界面原样显示）
    privacy_notice: str = ""        # 数据去向说明（界面原样显示；为空则不显示）

    @abstractmethod
    def status(self) -> dict:
        """是否可用。返回 make_status(...)。不得为检测而发起真实模型调用；应当很快返回（建议 < 10 秒）。"""

    @abstractmethod
    def start(self, env: dict | None = None) -> bool:
        """预热（可选的优化）。env 为软件传入的环境变量（含确认服务的端口与一次性口令，见文档）。返回是否成功。"""

    @abstractmethod
    def send(self, text: str, on_event: EventCallback, **options) -> None:
        """发送一条用户消息，流式回调事件，直到本轮结束。必须以且仅以一个 done 事件收尾；出错也要先发 error 再发 done。"""

    @abstractmethod
    def stop(self) -> None:
        """中断正在进行的这一轮（可从其他线程调用）。会话要保留：之后还能继续 send()。被中断的那轮发 stopped 再发 done。"""

    @abstractmethod
    def reset(self) -> None:
        """新对话：清空上下文。"""

    @abstractmethod
    def close(self) -> None:
        """退出软件时释放进程与连接。"""
