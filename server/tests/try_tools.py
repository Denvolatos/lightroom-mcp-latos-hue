"""End-to-end check against a real Lightroom: hosts the bridge in this process, waits for the plug-in to
connect, then calls every command through the same code path the MCP tools use.

Stop the dev bridge first (both use port 58770). Usage: python try_tools.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp import config, previews  # noqa: E402
from lightroom_mcp.bridge import Bridge, BridgeBusy  # noqa: E402


def show(title, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 1
    try:
        print("waiting for the plug-in to connect (up to 40 s)...")
        if not bridge.wait_connected(40):
            print("plug-in did not connect")
            return 1
        print("connected, plug-in version:", bridge.plugin_version)

        show("status", bridge.call("status"))
        listing = bridge.call("list_selected", {"limit": 20})
        show("list_selected", listing)
        if not listing.get("photos"):
            print("no selected photo; nothing more to test")
            return 0
        photo_id = listing["photos"][0]["id"]

        show("get_develop (selected)", bridge.call("get_develop", {"photo": "selected"}))
        by_id = bridge.call("get_develop", {"photo": photo_id})
        print("\nget_develop by uuid works:", by_id["photo"]["id"] == photo_id)

        t0 = time.time()
        preview = bridge.call("get_preview", {"photo": photo_id, "long_edge": 1024}, timeout=60)
        print(f"\n=== get_preview ({time.time() - t0:.1f} s) ===")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        path = Path(preview["path"])
        print("file inside preview folder:", config.PREVIEW_DIR.resolve() in path.resolve().parents)
        show("analysis", previews.analyze(path))

        for bad in ("00000000-0000-0000-0000-000000000000", ):
            try:
                bridge.call("get_develop", {"photo": bad})
            except Exception as e:  # noqa: BLE001 - we want to see the message
                print("\nunknown id ->", type(e).__name__, e)
        try:
            bridge.call("delete_everything")
        except Exception as e:  # noqa: BLE001
            print("unknown command ->", type(e).__name__, e)
    finally:
        bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
