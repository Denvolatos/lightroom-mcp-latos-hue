"""Smoke test over real stdio: start the server command given on the command line, list its tools,
call lr_status (Lightroom need not be running) and print the results.

Usage: python smoke_stdio.py <command> [args...]      e.g.  python smoke_stdio.py build\\dist\\lrmcp\\lrmcp.exe
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(command=sys.argv[1], args=sys.argv[2:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            for t in tools.tools:
                ro = t.annotations.read_only_hint if t.annotations else None
                print(f"  {t.name}: read_only_hint={ro}")
            result = await session.call_tool("lr_status", {})
            print("lr_status ->", result.content[0].text[:300].replace("\n", " "))
            result = await session.call_tool("lr_get_develop", {"photo": "bad id with spaces"})
            print("lr_get_develop(bad) isError=", result.is_error, "|", result.content[0].text[:150].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
