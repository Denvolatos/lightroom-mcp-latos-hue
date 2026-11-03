"""Named versions of one photo: "save how this photo looks now under a name, come back to it later".

Local files only, in ``~/LrMcp/knowledge/versions/<photo id>/``: one JSON per version (the whole set of settings this project may
change, so a version can be written back) and a small preview picture so versions can be compared side by side. Nothing here
talks to Lightroom or to the network; ``edits.EditService`` does the writing, and the plug-in checks every value again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import config

MAX_VERSIONS_PER_PHOTO = 50
MAX_NAME = 40
MAX_NOTE = 200
MAX_THUMBNAIL_BYTES = 400_000
PHOTO_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class VersionError(RuntimeError):
    """Written for the user (Chinese)."""


def clean_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME or _CONTROL.search(name):
        raise VersionError(f"版本名要写 1 到 {MAX_NAME} 个字，不能含换行等控制字符。")
    return name.strip()


class VersionStore:
    def __init__(self, directory: Path = config.VERSIONS_DIR):
        self.directory = directory

    def _photo_dir(self, photo_id: str) -> Path:
        if not isinstance(photo_id, str) or not PHOTO_ID.match(photo_id):
            raise VersionError("照片 id 不合法。")
        return self.directory / photo_id

    @staticmethod
    def version_id(name: str) -> str:
        return "v-" + hashlib.sha1(name.casefold().encode("utf-8")).hexdigest()[:10]

    def save(self, photo_id: str, photo_name: str | None, name: str, note: str, settings: dict, thumbnail: bytes | None,
             overwrite: bool = False) -> dict:
        name = clean_name(name)
        note = str(note or "")
        if len(note) > MAX_NOTE or _CONTROL.search(note.replace("\n", " ")):
            raise VersionError(f"备注最多 {MAX_NOTE} 个字。")
        folder = self._photo_dir(photo_id)
        vid = self.version_id(name)
        path = folder / f"{vid}.json"
        existing = self.list(photo_id) if folder.is_dir() else []
        if path.exists() and not overwrite:
            raise VersionError(f"这张照片已经有叫“{name}”的版本。要覆盖它请用 overwrite=true，或者换一个名字。")
        if not path.exists() and len(existing) >= MAX_VERSIONS_PER_PHOTO:
            raise VersionError(f"一张照片最多存 {MAX_VERSIONS_PER_PHOTO} 个版本，请先删掉不要的。")
        if thumbnail is not None and (not thumbnail.startswith(b"\xff\xd8") or len(thumbnail) > MAX_THUMBNAIL_BYTES):
            thumbnail = None  # not a small JPEG: keep the version, skip the picture
        folder.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": 1, "version_id": vid, "name": name, "note": note, "photo_id": photo_id, "photo_name": photo_name,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "created_ns": time.time_ns(), "settings": settings,
            "has_thumbnail": thumbnail is not None,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        picture = folder / f"{vid}.jpg"
        if thumbnail is not None:
            picture.write_bytes(thumbnail)
        else:
            picture.unlink(missing_ok=True)
        return record

    def list(self, photo_id: str) -> list[dict]:
        folder = self._photo_dir(photo_id)
        rows = []
        if folder.is_dir():
            for f in folder.glob("v-*.json"):
                try:
                    record = json.loads(f.read_text(encoding="utf-8"))
                    rows.append(record)
                except (OSError, ValueError):
                    continue
        return sorted(rows, key=lambda r: (r.get("created_ns", 0), r.get("name", "")))

    def get(self, photo_id: str, name: str) -> dict:
        name = clean_name(name)
        path = self._photo_dir(photo_id) / f"{self.version_id(name)}.json"
        if not path.is_file():
            known = ", ".join(f"“{r['name']}”" for r in self.list(photo_id)) or "还没有保存过任何版本"
            raise VersionError(f"这张照片没有叫“{name}”的版本。已有的版本：{known}。")
        return json.loads(path.read_text(encoding="utf-8"))

    def thumbnail_path(self, photo_id: str, name: str) -> Path | None:
        path = self._photo_dir(photo_id) / f"{self.version_id(clean_name(name))}.jpg"
        return path if path.is_file() else None

    def delete(self, photo_id: str, name: str) -> None:
        record = self.get(photo_id, name)
        folder = self._photo_dir(photo_id)
        (folder / f"{record['version_id']}.json").unlink(missing_ok=True)
        (folder / f"{record['version_id']}.jpg").unlink(missing_ok=True)
