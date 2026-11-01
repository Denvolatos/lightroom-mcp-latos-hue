"""Smoke test over real stdio: start the server command given on the command line, list its tools,
call lr_status (Lightroom need not be running) and print the results.

Set SMOKE_FULL=1 with Lightroom open and the plug-in loaded to also call every tool and check the picture.

Usage: python smoke_stdio.py <command> [args...]      e.g.  python smoke_stdio.py build\\dist\\lrmcp\\lrmcp.exe
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def first_text(result) -> str:
    return next((c.text for c in result.content if getattr(c, "type", "") == "text"), "")


async def main() -> int:
    params = StdioServerParameters(command=sys.argv[1], args=sys.argv[2:])
    full = os.environ.get("SMOKE_FULL") == "1"
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            for t in tools.tools:
                ro = t.annotations.read_only_hint if t.annotations else None
                print(f"  {t.name}: read_only_hint={ro}")
            result = await session.call_tool("lr_status", {})
            print("lr_status ->", first_text(result)[:300].replace("\n", " "))
            result = await session.call_tool("lr_get_develop", {"photo": "bad id with spaces"})
            print("lr_get_develop(bad) is_error=", result.is_error, "|", first_text(result)[:150].replace("\n", " "))
            if not full:
                return 0

            listing = json.loads(first_text(await session.call_tool("lr_list_selected", {})))
            print("lr_list_selected -> count", listing["count"], [p["name"] for p in listing["photos"]])
            develop = json.loads(first_text(await session.call_tool("lr_get_develop", {"photo": "selected"})))
            print("lr_get_develop -> Exposure2012", develop["settings"].get("Exposure2012"), "WhiteBalance", develop["settings"].get("WhiteBalance"))
            preview = await session.call_tool("lr_get_preview", {"photo": "selected", "long_edge": 1024})
            kinds = [(c.type, len(getattr(c, "data", "") or "")) for c in preview.content]
            print("lr_get_preview content types/sizes:", kinds, "is_error=", preview.is_error)
            info = json.loads(first_text(preview))
            print("   stats notes:", info["stats"]["notes_heuristic"], "| mean", info["stats"]["mean_brightness_0_255"])
            doctor = await session.call_tool("lr_doctor", {})
            print("lr_doctor ->")
            print(first_text(doctor))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
