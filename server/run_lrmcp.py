# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""PyInstaller entry point (lrmcp.exe)."""
import sys

from lightroom_mcp.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
