"""Run a Lua test script inside Lightroom through dev_bridge.py and print its result.

Usage: python -I dev_run.py <name.lua> [timeout_seconds]
<name.lua> must exist in plugin/lrmcp.lrdevplugin/devscripts/ . Only the NAME is sent; the plug-in runs the file
from its own folder and refuses anything else.
"""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DIR = Path.home() / "LrMcp"
SCRIPTS = Path(__file__).resolve().parent.parent / "plugin" / "lrmcp.lrdevplugin" / "devscripts"
URL = "http://127.0.0.1:58770"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.lua", name) or not (SCRIPTS / name).is_file():
        print(f"script must be a plain file name that exists in {SCRIPTS}")
        return 2
    token = (DIR / "token").read_text(encoding="ascii").strip()
    req = urllib.request.Request(
        f"{URL}/submit?t={timeout}",
        data=name.encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 15) as r:
            print(r.read().decode("utf-8", "replace"))
            return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        return 1
    except OSError as e:
        print(f"cannot reach dev bridge: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
