"""逐项确认用的极小 MCP 服务（stdio）。

由 claude 的 --permission-prompt-tool 调用：每当一个写入类工具需要许可，claude 会调用本服务的 approve 工具。
本服务把请求通过 127.0.0.1 + 本轮一次性口令转给修图助手窗口，等待用户点击；超时、断线、口令错误一律视为拒绝。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ASK_TIMEOUT = 125   # 略长于窗口端 120 秒的等待


def ask_window(tool_name: str, tool_input: dict, tool_use_id: str = "") -> dict:
    """向窗口询问，返回 {"allow": bool, "message": str}。任何异常都按拒绝处理。"""
    port, token = os.environ.get("LRAPP_PORT", ""), os.environ.get("LRAPP_TOKEN", "")
    if not port or not token:
        return {"allow": False, "message": "未连接到修图助手窗口，已拒绝执行。"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/ask", method="POST",
        data=json.dumps({"tool_name": tool_name, "input": tool_input, "tool_use_id": tool_use_id},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=ASK_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {"allow": False, "message": "无法连接修图助手窗口，已拒绝执行。"}


def decision_json(answer: dict, tool_input: dict) -> str:
    """claude 要求的返回格式：allow 需带 updatedInput，deny 需带 message。"""
    if answer.get("allow") is True:
        return json.dumps({"behavior": "allow", "updatedInput": tool_input}, ensure_ascii=False)
    return json.dumps({"behavior": "deny", "message": str(answer.get("message") or "用户拒绝了该项调整。")},
                      ensure_ascii=False)


def main() -> None:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import TextContent

    mcp = MCPServer("lrapp_confirm")

    @mcp.tool()
    def approve(tool_name: str, input: dict, tool_use_id: str = "") -> list:
        """Permission prompt handler (internal)."""
        # 必须返回单个 text 块（返回 str 会被包成 {"result": ...}，claude 会判为无效）
        return [TextContent(type="text", text=decision_json(ask_window(tool_name, input, tool_use_id), input))]

    mcp.run()


if __name__ == "__main__":
    main()
