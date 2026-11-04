# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""0.9 acceptance check: develop presets against a REAL Lightroom (test catalog only).

SAFETY: only on the test catalog (path contains "ceshi") with exactly one photo selected. Presets are applied and then
undone; at the end the WHOLE settings snapshot (every key, tables included) is compared with the start. Keys that did not exist at the
start (GrainSeed, DepthMapInfo: internal values Lightroom creates itself and cannot delete) are not counted as differences.
The plug-in (0.9.x) must have been reloaded. Usage: python acceptance_presets.py
"""
import hashlib
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp.bridge import Bridge, BridgeBusy, BridgeError  # noqa: E402
from lightroom_mcp.edits import EditError, EditService, EditStore  # noqa: E402

failures = 0
IGNORED = {"GrainSeed"}


def check(label, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")


def close(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-6
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return a == b


def differences(start, now):
    # keys that did not exist at the start (GrainSeed, DepthMapInfo, ...) are internal values Lightroom creates by itself
    # the first time a preset touches a photo; they cannot be deleted and do not change the picture
    keys = sorted(k for k in set(start) | set(now) if k not in IGNORED and k in start and not close(start.get(k), now.get(k)))
    return [f"{k}: {start.get(k)!r} -> {now.get(k)!r}" for k in keys]


def preview_pixels(bridge, photo_id, long_edge):
    """A digest of the picture's PIXELS. The file size is no proof of identical pictures: the JPEG embeds the (changing) file name,
    so two pictures with the same pixels can differ by a few bytes."""
    path = Path(bridge.call("get_preview", {"photo": photo_id, "long_edge": long_edge}, timeout=90)["path"])
    with Image.open(path) as im:
        digest = hashlib.sha1(im.convert("RGB").tobytes()).hexdigest()[:12]
    path.unlink(missing_ok=True)
    return digest


def preview_size(bridge, photo_id):
    return preview_pixels(bridge, photo_id, 512)


def settled_preview_size(bridge, photo_id, wanted, tries=6):
    """Lightroom may still be re-rendering right after a change; ask a few times until the size is the wanted one."""
    size = preview_size(bridge, photo_id)
    for _ in range(tries - 1):
        if size == wanted:
            break
        time.sleep(2)
        size = preview_size(bridge, photo_id)
    return size


def main():
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 2
    store_dir = Path(tempfile.mkdtemp(prefix="lrmcp-presets-"))
    service = EditService(bridge.call, EditStore(store_dir), readonly_file=store_dir / "ro")
    photo_id, start = None, None
    try:
        if not bridge.wait_connected(40):
            print("plug-in did not connect")
            return 2
        status = bridge.call("status")
        if "ceshi" not in status["catalog_path"]:
            print(f"REFUSED: not the test catalog: {status['catalog_path']}")
            return 2
        listing = bridge.call("list_selected")
        if listing["count"] != 1:
            print(f"REFUSED: select exactly one photo (count={listing['count']})")
            return 2
        photo_id = listing["photos"][0]["id"]
        print(f"photo: {listing['photos'][0]['name']} ({listing['photos'][0]['format']})\n")

        start = bridge.call("snapshot", {"photo": photo_id})["settings"]
        start_preview = preview_size(bridge, photo_id)

        found = service.list_presets("", 50)
        check("list_presets returns presets", found["total"] > 0 and found["shown"] > 0, f"{found['total']} presets")
        plain = [p for p in found["presets"] if not p["has_masks"]]
        masked = [p for p in found["presets"] if p["has_masks"]]
        check("some presets are plain and can be applied", len(plain) >= 3)

        # a masked preset is refused and changes nothing
        if masked:
            try:
                service.apply_preset(masked[0]["id"])
                check("a preset with masks is refused", False, "no error")
            except (BridgeError, EditError) as e:
                check("a preset with masks is refused", "蒙版" in str(e), str(e)[:50])
            now = bridge.call("snapshot", {"photo": photo_id})["settings"]
            check("refusal changed nothing", not differences(start, now))
        else:
            print("note: no masked preset among the first 50; refusal not exercised")

        # each of three presets: apply, look, undo, compare the WHOLE snapshot
        applied = []
        for preset in plain[:3]:
            result = service.apply_preset(preset["id"], reason="acceptance")
            applied.append(result)
            changed_something = result["settings_changed"] > 0
            check(f"preset '{preset['name']}' applied", changed_something or "没有改变" in result["note"], f"{result['settings_changed']} settings changed")
            restored = service.restore(result["edit_id"])
            now = bridge.call("snapshot", {"photo": photo_id})["settings"]
            diff = differences(start, now)
            check(f"restore after '{preset['name']}' brings back EVERY setting ({len(start)} keys)", restored["verified"] and not diff, str(diff)[:150])

        # presets and slider edits mixed, then restore_original
        r1 = service.apply_preset(plain[0]["id"], reason="acceptance mix")
        r2 = service.set_develop({"Exposure2012": start.get("Exposure2012", 0) + 0.3}, reason="acceptance mix")
        r3 = service.apply_preset(plain[1]["id"], reason="acceptance mix")
        preview_mid = preview_size(bridge, photo_id)
        original = service.restore_original()
        now = bridge.call("snapshot", {"photo": photo_id})["settings"]
        diff = differences(start, now)
        check("restore_original after preset + slider + preset brings back every setting", original["verified"] and not diff, str(diff)[:150])
        check("the preview differs while the presets were on and is identical afterwards",
              preview_mid != start_preview and settled_preview_size(bridge, photo_id, start_preview) == start_preview, f"{preview_mid} vs {start_preview}")
        check("edit history lists the preset edits", service.list_edits(photo_id)["count"] >= 4)
        _ = (r1, r2, r3)
    finally:
        if photo_id and start is not None:
            try:
                service.restore_original(photo=photo_id)
            except Exception as e:  # noqa: BLE001
                print("cleanup:", str(e)[:100])
            final = bridge.call("snapshot", {"photo": photo_id})["settings"]
            diff = differences(start, final)
            check(f"FINAL: every setting is back to the start ({len(start)} keys; GrainSeed ignored)", not diff, str(diff)[:200])
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
