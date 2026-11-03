"""Codex 命令行来源：给贡献者的起点（骨架，尚未实现，注册表里标为不可用）。

接入步骤见 docs/AI来源接口.md。以下每一项都需要贡献者在真机上核对，核对前一律视为"待验证"。
"""
from __future__ import annotations

from .base import AIProvider, UNAVAILABLE, make_status


class CodexProvider(AIProvider):
    id = "codex"
    display_name = "Codex 命令行"
    supports_images = False      # TODO（待验证）：codex 能否接收 lr_get_preview 返回的图片，决定此项

    def status(self) -> dict:
        # TODO：检测 codex 是否已安装、是否已登录，且不得为检测而发起真实模型调用
        # （待验证：codex 是否有类似 `claude auth status` 的本地命令）。
        return make_status(False, UNAVAILABLE, "Codex 命令行——后续提供，欢迎贡献。", "详见 docs/AI来源接口.md。")

    def start(self, env=None) -> bool:
        # TODO：预热（可选）。env 含确认服务的端口与口令（LRAPP_PORT / LRAPP_TOKEN），需原样传给子进程。
        raise NotImplementedError

    def send(self, text, on_event, **options) -> None:
        # TODO 逐项核对：
        # 1. `codex exec` 的输出格式（是否有逐行 JSON 流？字段名？）——翻译成 base.py 里的事件：
        #    文字增量 -> text；工具调用 -> tool（name 去掉服务前缀）；工具结果 -> tool_result；结束 -> done。
        # 2. 怎么多轮续接（是否有 resume / session 概念），否则需自己拼上下文。
        # 3. 怎么把 Lightroom 工具交给 codex：可复用 claude_bridge.lightroom_server_config() 的 MCP 启动配置；
        #    codex 的 MCP 配置写法（待验证）。只开放白名单工具：claude_bridge.READONLY_TOOLS + ENABLED_WRITE_TOOLS。
        # 4. 逐项确认怎么接（见文档"逐项确认"一节）：codex 有无类似 permission-prompt 的机制（待验证），
        #    没有就退回"软件在转发工具调用前先询问"。
        # 5. 用量怎么报告：tokens / cost 取不到就填 0 / None，不得编造。
        # 6. 错误映射为中文（可参考 claude_bridge.friendly_error 的口径）。
        raise NotImplementedError

    def stop(self) -> None:
        # TODO：怎么中断当前这一轮并保留会话（信号？子进程重建后续接？），待验证。
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
