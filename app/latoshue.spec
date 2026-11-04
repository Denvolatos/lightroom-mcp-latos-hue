# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
# PyInstaller spec for Latos Hue (run through build_app.ps1). Two executables share one dependency folder:
#   LatosHue.exe          windowed (no console) - the GUI
#   latoshue-helper.exe   console - helper processes started by the app (--lr-launcher, --permission-server, --codex-proxy)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

app_dir = os.path.abspath(SPECPATH)
repo = os.path.dirname(app_dir)
icon = os.path.join(app_dir, "web", "assets", "latos-hue-ribbon.ico")

datas = [(os.path.join(app_dir, "web"), "web")]
binaries = []
hiddenimports = collect_submodules("lightroom_mcp") + collect_submodules("providers")
for pkg in ("webview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(app_dir, "run_latoshue.py")],
    pathex=[app_dir, os.path.join(repo, "server")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["mcp.cli", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LatosHue", console=False, icon=icon)
helper = EXE(pyz, a.scripts, [], exclude_binaries=True, name="latoshue-helper", console=True, icon=icon)
coll = COLLECT(gui, helper, a.binaries, a.datas, name="LatosHue")
