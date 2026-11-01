"""Changing develop settings safely (v1.1): what may be changed, backups of the old values, restore.

Rules (each one was measured on Lightroom Classic 15.2, see docs/实验记录.md):
* only whitelisted sliders, within range, and only a limited step per call;
* before anything is written the old values are saved to disk (``~/LrMcp/edits/<id>.json``);
* restoring = writing the saved values back (Lightroom snapshots and undo were found unreliable);
* a read-only switch (file ``~/LrMcp/readonly`` or ``LRMCP_READONLY=1``) refuses every write.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from pathlib import Path
from typing import Callable

from . import config

COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
GLOBAL_KEYS = (
    "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation",
)
HSL_PREFIXES = ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")

# key -> (minimum, maximum, largest change in one call). Keep in sync with plugin/.../Limits.lua (a test compares).
LIMITS: dict[str, tuple[float, float, float]] = {
    "Exposure2012": (-5.0, 5.0, 1.0),
    "Temperature": (2000.0, 50000.0, 1000.0),  # kelvin, RAW photos only
    "Tint": (-150.0, 150.0, 30.0),
}
WB_KEYS = ("Temperature", "Tint")
WB_LABELS = ("As Shot", "Auto", "Daylight", "Cloudy", "Shade", "Tungsten", "Fluorescent", "Flash", "Custom")
for _key in GLOBAL_KEYS:
    LIMITS[_key] = (-100.0, 100.0, 30.0)
for _prefix in HSL_PREFIXES:
    for _color in COLORS:
        LIMITS[_prefix + _color] = (-100.0, 100.0, 30.0)

EDIT_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")

_last_ns = 0


def _now_ns() -> int:
    """Strictly increasing timestamp. The edit id only has second resolution and a random suffix, so the order of
    edits (which decides what 'the original value' is) must not depend on it."""
    global _last_ns
    _last_ns = max(time.time_ns(), _last_ns + 1)
    return _last_ns


class ReadOnlyError(RuntimeError):
    """Writing is switched off."""


class EditError(RuntimeError):
    """A change was refused or could not be completed; the message is written for the user (Chinese)."""


def describe_limits() -> str:
    """One compact text for the tool description."""
    lines = ["Exposure2012：-5 到 +5，单次最多改 ±1.0"]
    lines.append("白平衡（只限 RAW 照片，JPEG 没有开尔文值）：Temperature 色温 2000 到 50000（单位 K，数字越大画面越偏暖），"
                 "单次最多改 ±1000；Tint 色调 -150 到 +150（负偏绿、正偏洋红），单次最多改 ±30")
    lines.append("对比度/高光/阴影/白色/黑色/纹理/清晰度/去朦胧/自然饱和度/饱和度（Contrast2012, Highlights2012, Shadows2012, "
                 "Whites2012, Blacks2012, Texture, Clarity2012, Dehaze, Vibrance, Saturation）：-100 到 +100，单次最多改 ±30")
    lines.append("HSL（HueAdjustment / SaturationAdjustment / LuminanceAdjustment + Red, Orange, Yellow, Green, Aqua, Blue, "
                 "Purple, Magenta）：-100 到 +100，单次最多改 ±30")
    return "\n".join(lines)


def validate_changes(changes: object) -> dict[str, float]:
    """Check keys, types and ranges. The per-call step limit is enforced by the plug-in (it knows the current value)."""
    if not isinstance(changes, dict) or not changes:
        raise EditError("changes 必须是非空的 {参数名: 数值} 字典，例如 {\"Exposure2012\": 0.3}。")
    if len(changes) > config.MAX_KEYS_PER_EDIT:
        raise EditError(f"一次最多改 {config.MAX_KEYS_PER_EDIT} 个参数，你给了 {len(changes)} 个。请分几次改。")
    clean: dict[str, float] = {}
    for key, value in changes.items():
        if key not in LIMITS:
            raise EditError(
                f"不允许修改“{key}”。当前版本只允许这些：\n{describe_limits()}\n（色调曲线、蒙版、裁剪、预设暂不支持。）"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise EditError(f"{key} 的值必须是有限的数字，你给的是 {value!r}。")
        low, high, _ = LIMITS[key]
        if value < low or value > high:
            raise EditError(f"{key} 的取值范围是 {low:g} 到 {high:g}，你给的是 {value:g}。")
        clean[key] = float(value)
    return clean


def fmt(value: float) -> str:
    """Number as text for the plug-in command line (no spaces, no locale)."""
    return format(float(value), ".10g")


def current_values(develop: dict, keys) -> dict[str, float]:
    """Pick the current value of each wanted key out of a ``get_develop`` reply."""
    out: dict[str, float] = {}
    for key in keys:
        value = None
        for prefix, field in (("HueAdjustment", "hue"), ("SaturationAdjustment", "saturation"), ("LuminanceAdjustment", "luminance")):
            if key.startswith(prefix):
                value = develop.get("hsl", {}).get(key[len(prefix):], {}).get(field)
                break
        else:
            value = develop.get("settings", {}).get(key)
        if not isinstance(value, (int, float)):
            if key in WB_KEYS:
                raise EditError("这张照片读不到色温/色调的当前值（JPEG 没有开尔文值；没编辑过的 RAW 也可能读不到，"
                                "先在 Lightroom 里对它做任意一次编辑再试），已取消修改。")
            raise EditError(f"读不到 {key} 的当前值，已取消修改。")
        out[key] = float(value)
    return out


class EditStore:
    """One JSON file per change in ``directory``."""

    def __init__(self, directory: Path = config.EDIT_DIR):
        self.directory = directory

    def new_id(self) -> str:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)

    def _path(self, edit_id: str) -> Path:
        if not EDIT_ID.match(edit_id):
            raise EditError(f"修改编号“{edit_id}”不合法（应形如 20261102-120000-ab12）。")
        return self.directory / f"{edit_id}.json"

    def save(self, record: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(record["edit_id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, edit_id: str) -> dict:
        path = self._path(edit_id)
        if not path.is_file():
            raise EditError(f"没有找到修改记录 {edit_id}。用 lr_list_edits 查看已有的记录。")
        return json.loads(path.read_text(encoding="utf-8"))

    def all(self) -> list[dict]:
        records = []
        if self.directory.is_dir():
            for f in self.directory.glob("*.json"):
                try:
                    records.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    pass
        return sorted(records, key=lambda r: (r.get("created_ns", 0), r.get("edit_id", "")))


Call = Callable[..., dict]


class EditService:
    """The logic behind lr_set_develop / lr_restore / lr_restore_original / lr_list_edits.

    ``call(command, params, timeout)`` talks to the plug-in (``Bridge.call``).
    """

    def __init__(self, call: Call, store: EditStore | None = None, readonly_file: Path = config.READONLY_FILE):
        self.call = call
        self.store = store or EditStore()
        self.readonly_file = readonly_file

    # ---- guards ----------------------------------------------------
    def check_writable(self) -> None:
        if self.readonly_file.exists() or os.environ.get("LRMCP_READONLY") == "1":
            raise ReadOnlyError(
                "只读模式已开启，不允许修改照片。要关闭它：删除文件 "
                f"{self.readonly_file}（并确认环境变量 LRMCP_READONLY 不是 1）。"
            )

    # ---- helpers ---------------------------------------------------
    def _resolve_photo(self, photo: str) -> tuple[str, dict]:
        """Return (uuid, develop reply) for 'selected' or a uuid, so later steps use one fixed photo."""
        develop = self.call("get_develop", {"photo": photo}, timeout=30)
        return develop["photo"]["id"], develop

    def _write(self, photo_id: str, edit_id: str, values: dict[str, float], restoring: bool, wb: str | None = None) -> dict:
        params = {"photo": photo_id, "edit": edit_id}
        if restoring:
            params["restore"] = "1"
            if wb in WB_LABELS and any(k in WB_KEYS for k in values):
                params["wb"] = wb.replace(" ", "_")  # the command line is split at spaces
        params.update({k: fmt(v) for k, v in values.items()})
        return self.call("set_develop", params, timeout=60)

    @staticmethod
    def _summary(before: dict, after: dict, requested: dict) -> list[dict]:
        rows = []
        for key, want in requested.items():
            got = after.get(key)
            rows.append({
                "parameter": key,
                "before": before.get(key),
                "requested": want,
                "after": got,
                "ok": isinstance(got, (int, float)) and abs(got - want) < 1e-3,
            })
        return rows

    # ---- the four operations ---------------------------------------
    def set_develop(self, changes: dict, reason: str = "", photo: str = "selected") -> dict:
        self.check_writable()
        wanted = validate_changes(changes)
        photo_id, develop = self._resolve_photo(photo)
        before_pre = current_values(develop, wanted)

        record = {
            "edit_id": self.store.new_id(), "kind": "set", "status": "pending",
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "created_ns": _now_ns(),
            "photo_id": photo_id, "photo_name": develop["photo"].get("name"),
            "reason": str(reason)[:500], "requested": wanted, "before": before_pre,
        }
        if any(k in WB_KEYS for k in wanted):
            record["before_wb"] = develop.get("settings", {}).get("WhiteBalance")
        self.store.save(record)  # the old values are on disk BEFORE anything is written
        try:
            data = self._write(photo_id, record["edit_id"], wanted, restoring=False)
        except Exception as e:
            record.update(status="failed", error=str(e))
            self.store.save(record)
            raise
        record.update(status="applied", before=data.get("before", before_pre), after=data.get("after", {}),
                      verified=bool(data.get("verified")))
        self.store.save(record)
        return {
            "edit_id": record["edit_id"],
            "photo": record["photo_name"],
            "photo_id": photo_id,
            "verified": record["verified"],
            "changes": self._summary(record["before"], record["after"], wanted),
            "undo": f"lr_restore(edit_id=\"{record['edit_id']}\") 写回这次修改前的值；"
                    "lr_restore_original 写回 LrMCP 第一次改这张照片之前的值。",
        }

    def restore(self, edit_id: str) -> dict:
        self.check_writable()
        record = self.store.load(edit_id)
        if record.get("kind") != "set":
            raise EditError("这条记录本身是一次还原，不能再还原。")
        if record.get("restored_by"):
            return {"edit_id": edit_id, "note": f"这次修改已经在 {record['restored_by']} 里还原过了，没有再做任何事。"}
        if record.get("status") == "failed":
            raise EditError("这次修改当时失败了，没有改动照片，不需要还原。")
        values = {k: float(v) for k, v in record["before"].items()}
        new_id = self.store.new_id()
        data = self._write(record["photo_id"], new_id, values, restoring=True, wb=record.get("before_wb"))
        self.store.save({
            "edit_id": new_id, "kind": "restore", "status": "applied", "of": [edit_id],
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "created_ns": _now_ns(), "photo_id": record["photo_id"],
            "photo_name": record.get("photo_name"), "requested": values,
            "before": data.get("before", {}), "after": data.get("after", {}), "verified": bool(data.get("verified")),
        })
        record["restored_by"] = new_id
        self.store.save(record)
        return {
            "edit_id": new_id, "restored": edit_id, "photo": record.get("photo_name"),
            "verified": bool(data.get("verified")),
            "changes": self._summary(data.get("before", {}), data.get("after", {}), values),
        }

    def restore_original(self, photo: str = "selected", dry_run: bool = False) -> dict:
        if not dry_run:
            self.check_writable()
        if photo == "selected":
            listing = self.call("list_selected", {"limit": 1}, timeout=30)
            if not listing.get("active_id"):
                raise EditError("Lightroom 里没有选中的照片。")
            photo_id = listing["active_id"]
        else:
            photo_id = photo
        records = [r for r in self.store.all()
                   if r.get("photo_id") == photo_id and r.get("kind") == "set"
                   and r.get("status") in ("applied", "pending") and not r.get("restored_by")]
        if not records:
            return {"photo_id": photo_id, "note": "没有 LrMCP 改过这张照片（或都已还原），无需还原。"}
        earliest: dict[str, float] = {}
        earliest_wb: str | None = None
        for r in records:  # records are sorted oldest first: keep the first old value of each slider
            for key, value in r.get("before", {}).items():
                earliest.setdefault(key, float(value))
            if earliest_wb is None and r.get("before_wb"):
                earliest_wb = r["before_wb"]
        plan = {"photo": records[0].get("photo_name"), "edits_undone": [r["edit_id"] for r in records], "will_write": earliest}
        if dry_run:
            return {**plan, "dry_run": True,
                    "warning": "会把这些滑块写回 LrMCP 第一次改动之前的值；如果你期间手动改过同一个滑块，也会被覆盖。"}
        new_id = self.store.new_id()
        data = self._write(photo_id, new_id, earliest, restoring=True, wb=earliest_wb)
        self.store.save({
            "edit_id": new_id, "kind": "restore", "status": "applied", "of": plan["edits_undone"],
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "created_ns": _now_ns(), "photo_id": photo_id, "photo_name": plan["photo"],
            "requested": earliest, "before": data.get("before", {}), "after": data.get("after", {}),
            "verified": bool(data.get("verified")),
        })
        for r in records:
            r["restored_by"] = new_id
            self.store.save(r)
        return {
            "edit_id": new_id, "photo": plan["photo"], "edits_undone": plan["edits_undone"],
            "verified": bool(data.get("verified")),
            "changes": self._summary(data.get("before", {}), data.get("after", {}), earliest),
        }

    def list_edits(self, photo: str = "all", limit: int = 20) -> dict:
        records = self.store.all()
        if photo != "all":
            if photo == "selected":
                photo = self.call("list_selected", {"limit": 1}, timeout=30).get("active_id") or ""
            records = [r for r in records if r.get("photo_id") == photo]
        rows = [{
            "edit_id": r["edit_id"], "kind": r.get("kind"), "status": r.get("status"), "time": r.get("created"),
            "photo": r.get("photo_name"), "reason": r.get("reason", ""),
            "parameters": r.get("requested", {}), "restored_by": r.get("restored_by"),
        } for r in reversed(records)][: max(1, min(int(limit), 100))]
        return {"count": len(rows), "edits": rows}
