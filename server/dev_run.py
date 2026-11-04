# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
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


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.lua", name) or not (SCRIPTS / name).is_file():
        print(f"script must be a plain file name that exists in {SCRIPTS}")
        return 2
    info = dict(line.split("=", 1) for line in (DIR / "dev_server.txt").read_text(encoding="ascii").split() if "=" in line)
    token, url = info["token"], f"http://127.0.0.1:{info['port']}"
    req = urllib.request.Request(
        f"{url}/submit?t={timeout}",
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
