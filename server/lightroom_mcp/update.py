"""Update notice: once a day, ask GitHub whether a newer release exists. Nothing is downloaded or installed.

The only request is an anonymous HTTPS GET of the public "latest release" page of this project (no data about the
user, the photos or Lightroom is sent; GitHub sees the usual IP address and the User-Agent "lrmcp/<version>").
Switch it off with the environment variable LRMCP_NO_UPDATE_CHECK=1 or by creating the file ~/LrMcp/no_update_check.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__, config

LATEST_URL = "https://api.github.com/repos/Denvolatos/lightroom-mcp-win/releases/latest"
RELEASES_PAGE = "https://github.com/Denvolatos/lightroom-mcp-win/releases/latest"
CHECK_EVERY_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 5.0
_TAG = re.compile(r"^v?(\d{1,4})\.(\d{1,5})\.(\d{1,5})$")
log = logging.getLogger("lrmcp")


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _TAG.match(str(text).strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def disabled(data_dir: Path = config.DATA_DIR) -> bool:
    return os.environ.get("LRMCP_NO_UPDATE_CHECK") == "1" or (data_dir / "no_update_check").exists()


def fetch_latest_tag() -> str:
    request = urllib.request.Request(
        LATEST_URL, headers={"User-Agent": f"lrmcp/{__version__}", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
        return str(json.loads(response.read(200_000)).get("tag_name", ""))


class UpdateChecker:
    """Remembers the answer in <data_dir>/update_check.json so a restart within a day does not ask again."""

    def __init__(self, data_dir: Path = config.DATA_DIR, fetch=fetch_latest_tag, current: str = __version__):
        self.data_dir, self.fetch, self.current = data_dir, fetch, current
        self.cache = data_dir / "update_check.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self.cache.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def check_now(self) -> None:
        """Asks GitHub unless the last answer is younger than a day. Never raises."""
        if disabled(self.data_dir):
            return
        cached = self._read()
        if time.time() - float(cached.get("checked_at", 0) or 0) < CHECK_EVERY_SECONDS:
            return
        try:
            tag = self.fetch()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps({"checked_at": time.time(), "latest": tag}), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - offline, rate limited, ... : just try again tomorrow
            log.info("update check failed: %s", e)

    def start_in_background(self) -> None:
        threading.Thread(target=self.check_now, name="lrmcp-update-check", daemon=True).start()

    def notice(self) -> str | None:
        """A one-line message if a newer release is known, else None."""
        if disabled(self.data_dir):
            return None
        latest = str(self._read().get("latest", ""))
        if is_newer(latest, self.current):
            return f"有新版本 {latest.lstrip('v')}（当前 {self.current}）：{RELEASES_PAGE} 。不会自动更新，请告诉用户，由用户决定是否下载安装。"
        return None
