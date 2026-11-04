# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Expose only the Lightroom tools used by the app, with write confirmation enforced here."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

from claude_bridge import ENABLED_WRITE_TOOLS, READONLY_TOOLS, lightroom_server_config

ALLOWED = frozenset(READONLY_TOOLS + ENABLED_WRITE_TOOLS)
WRITES = frozenset(ENABLED_WRITE_TOOLS)


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


def _confirm(name: str, arguments: dict) -> bool:
    """Fail closed when the app's confirmation endpoint is absent or rejects a write."""
    port, token = os.environ.get("LRAPP_PORT", ""), os.environ.get("LRAPP_TOKEN", "")
    if not port.isdecimal() or not 0 < int(port) < 65536 or not token:
        return False
    body = json.dumps({"tool_name": f"mcp__lightroom_mcp__{name}", "input": arguments,
                       "tool_use_id": ""}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/ask", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=125) as response:
            return json.load(response).get("allow") is True
    except (OSError, ValueError, TypeError):
        return False


async def main() -> None:
    config = lightroom_server_config()
    child_env = {k: v for k, v in os.environ.items() if k not in ("LRAPP_PORT", "LRAPP_TOKEN")}
    child_env.update(config.get("env", {}))
    params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=child_env)
    async with stdio_client(params) as (child_read, child_write):
        async with ClientSession(child_read, child_write) as child:
            await child.initialize()
            catalog = await child.list_tools()
            tools = [tool for tool in catalog.tools if tool.name in ALLOWED]

            async def list_tools(_context, _params):
                return types.ListToolsResult(tools=tools)

            async def call_tool(_context, request):
                name, arguments = request.name, request.arguments or {}
                if name not in ALLOWED:
                    return _error("此工具未获授权，未执行。")
                if name in WRITES and not await asyncio.to_thread(_confirm, name, arguments):
                    return _error("未获用户确认，已视为拒绝，未执行。")
                return await child.call_tool(name, arguments, read_timeout_seconds=130)

            server = Server("lightroom_mcp", on_list_tools=list_tools, on_call_tool=call_tool)
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
