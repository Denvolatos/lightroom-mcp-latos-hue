# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Compile every plug-in Lua file with a Lua 5.1 interpreter (the version Lightroom uses) to catch syntax errors
before the plug-in is loaded into Lightroom. Needs the optional package ``lupa`` (pip install lupa).

Usage: python lua_syntax.py
"""
import sys
from pathlib import Path

try:
    from lupa.lua51 import LuaRuntime
except ImportError:  # pragma: no cover
    print("lupa is not installed (pip install lupa); skipping")
    sys.exit(0)

PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "lrmcp.lrdevplugin"
lua = LuaRuntime()
check = lua.eval("function(code, name) local f, err = loadstring(code, name) return err end")

failures = 0
for path in sorted(PLUGIN.rglob("*.lua")):
    err = check(path.read_text(encoding="utf-8"), "@" + path.name)
    print(("OK      " if err is None else "SYNTAX  ") + str(path.relative_to(PLUGIN)) + ("" if err is None else f": {err}"))
    failures += err is not None
sys.exit(1 if failures else 0)
