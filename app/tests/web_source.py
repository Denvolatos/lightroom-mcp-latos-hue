# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Shared helpers for tests that need the text or the static files of the web UI (app/web).

index.html only holds the page structure; styles live in css/app.css and the scripts in js/*.js (classic scripts,
shared global scope, loaded in the order of the <script src> tags). The ui_*_check.py scripts serve the page from a
local static server: ``inject_stub`` puts a fake pywebview.api in front of the first page script and ``serve_static``
answers the css/ and js/ requests. ``web_source`` returns index.html + css + js as one text for tests that grep it.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
INDEX = WEB_DIR / "index.html"
_LINK_RE = re.compile(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"')
_SCRIPT_RE = re.compile(r'<script src="([^"]+)"></script>')
_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


def read_index() -> str:
    return INDEX.read_text(encoding="utf-8")


def stylesheet_paths(html: str | None = None) -> list[str]:
    return _LINK_RE.findall(read_index() if html is None else html)


def script_paths(html: str | None = None) -> list[str]:
    """The page scripts, in load order."""
    return _SCRIPT_RE.findall(read_index() if html is None else html)


def web_source() -> str:
    """index.html + every stylesheet + every script (in load order) as one text."""
    parts = [read_index()]
    parts += [(WEB_DIR / p).read_text(encoding="utf-8") for p in stylesheet_paths(parts[0]) + script_paths(parts[0])]
    return "\n".join(parts)


def inject_stub(html: str, stub: str) -> str:
    """Put ``stub`` (a fake pywebview.api <script>) right before the first page script."""
    m = _SCRIPT_RE.search(html)
    assert m, "index.html has no <script src=...>"
    return html[:m.start()] + stub + "\n" + html[m.start():]


def serve_static(handler) -> bool:
    """Answer GET /css/... and /js/... from app/web. Returns True when the request was handled."""
    path = handler.path.split("?")[0]
    if not (path.startswith("/css/") or path.startswith("/js/")):
        return False
    f = (WEB_DIR / path.lstrip("/")).resolve()
    if WEB_DIR.resolve() not in f.parents or f.suffix not in _TYPES or not f.is_file():
        handler.send_response(404)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True
    data = f.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", _TYPES[f.suffix])
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
    return True
