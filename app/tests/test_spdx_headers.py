# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Every own source file must start with the SPDX licence header (see DEV_NOTES, "SPDX headers").

Scope (must match DEV_NOTES): app/ server/ plugin/ *.py *.lua; experiments/ *.lua; root and installer/ *.ps1 *.iss;
server/*.ps1; app/web/index.html; app/latoshue.spec.
Left out on purpose: .bat (kept short and pure ASCII), LICENSE, *.md, *.txt, images/icons, data files,
build/ (generated), docs/, hidden folders and caches.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = "SPDX-License-Identifier: AGPL-3.0-only"
COPYRIGHT = "Copyright (C) 2026 Denvolatos and contributors"
SKIP_DIRS = {"build", "docs", "__pycache__", "node_modules", "dist"}
EXPLICIT = {"app/web/index.html", "app/latoshue.spec"}


def _in_scope(rel: str) -> bool:
    parts = rel.split("/")
    ext = os.path.splitext(rel)[1].lower()
    if parts[0] in ("app", "server", "plugin") and ext in (".py", ".lua"):
        return True
    if parts[0] == "experiments" and ext == ".lua":
        return True
    if ext == ".ps1" and len(parts) <= 2 and parts[0] in (parts[-1], "server"):
        return True
    if parts[0] == "installer" and ext == ".iss":
        return True
    return rel in EXPLICIT


def _files() -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(ROOT).as_posix()
            if _in_scope(rel):
                out.append(rel)
    return sorted(out)


def test_scope_is_not_empty():
    files = _files()
    assert len(files) > 100
    assert "app/web/index.html" in files and "build.ps1" in files and "installer/latoshue.iss" in files


def test_all_own_sources_have_spdx_header():
    missing = []
    for rel in _files():
        head = (ROOT / rel).read_bytes()[:1000].decode("utf-8", "replace")
        if MARKER not in head or COPYRIGHT not in head:
            missing.append(rel)
    assert not missing, "missing SPDX header (add the two header lines): " + ", ".join(missing)
