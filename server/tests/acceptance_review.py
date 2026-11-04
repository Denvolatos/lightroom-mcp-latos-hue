# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""0.12 acceptance check: review, before/after previews, restore conflict protection and reuse of an edit, against a REAL
Lightroom (test catalog only).

SAFETY: only on the test catalog (path contains "ceshi") with 2 to 4 photos selected. Everything is undone at the end and the
WHOLE settings snapshot of every photo is compared with the start (keys that did not exist at the start are internal values
Lightroom creates by itself and are not counted). Do not click in Lightroom while this runs: the selection must not change.
The plug-in must be loaded. Usage: python acceptance_review.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp import tools  # noqa: E402
from lightroom_mcp.bridge import Bridge, BridgeBusy  # noqa: E402
from lightroom_mcp.edits import EditError, EditService, EditStore  # noqa: E402

failures = 0


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
    return sorted(k for k in start if not close(start.get(k), now.get(k)))


def main():
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 2
    store_dir = Path(tempfile.mkdtemp(prefix="lrmcp-review-"))
    store = EditStore(store_dir)
    service = EditService(bridge.call, store, readonly_file=store_dir / "ro")
    starts = {}
    try:
        if not bridge.wait_connected(40):
            print("plug-in did not connect")
            return 2
        status = bridge.call("status")
        if "ceshi" not in status["catalog_path"]:
            print(f"REFUSED: not the test catalog: {status['catalog_path']}")
            return 2
        listing = bridge.call("list_selected")
        if not 2 <= listing["count"] <= 4:
            print(f"REFUSED: select 2 to 4 photos (count={listing['count']})")
            return 2
        photos = listing["photos"]
        first = listing["active_id"] or photos[0]["id"]
        for p in photos:
            starts[p["id"]] = bridge.call("snapshot", {"photo": p["id"]})["settings"]
        print("photos: " + ", ".join(f"{p['name']} ({p['format']})" for p in photos) + "\n")

        # the MCP tools, built on top of the real bridge but with a throw-away edit history
        tools.EditService = lambda call: EditService(call, store, readonly_file=store_dir / "ro")
        server = tools.build_server(bridge)

        # 1. review of the selected photos
        review = asyncio.run(server.call_tool("lr_review_selected", {"limit": len(photos), "long_edge": 512}))
        info = json.loads(review.content[0].text)
        check("lr_review_selected: one image per selected photo, in order", info["shown"] == len(photos)
              and [c.type for c in review.content] == ["text"] + ["image"] * len(photos) and info["image_order"] == [p["id"] for p in info["photos"]])

        # 2. before / after previews with numbers
        base = starts[first]["Exposure2012"]
        result = asyncio.run(server.call_tool("lr_set_develop", {"changes": {"Exposure2012": base + 0.5}, "photo": first, "preview": True, "reason": "acceptance review"}))
        out = json.loads(result.content[0].text)
        check("preview=true returns before and after images", [c.type for c in result.content] == ["text", "image", "image"] and out["image_order"] == ["before", "after"])
        check("the numbers show the picture got brighter", out["preview_delta"]["mean_brightness_0_255"] > 0, str(out["preview_delta"]))
        set_edit = out["edit_id"]

        # 3. restore refuses to overwrite a later (manual) change, unless forced
        manual = base + 0.8
        bridge.call("set_develop", {"photo": first, "edit": "manual-test", "Exposure2012": f"{manual:g}"})
        try:
            service.restore(set_edit)
            check("restore refuses after a later manual change", False, "no error")
        except EditError as e:
            check("restore refuses after a later manual change", "force=true" in str(e), str(e)[:80])
        held = bridge.call("get_develop", {"photo": first})["settings"]["Exposure2012"]
        check("the manual value was not overwritten", abs(held - manual) < 1e-3)
        forced = service.restore(set_edit, force=True)
        back = bridge.call("get_develop", {"photo": first})["settings"]["Exposure2012"]
        check("force=true restores to the value from before the edit", forced["verified"] and abs(back - base) < 1e-3)

        # 4. reuse a verified edit on the other selected photos (dry run first)
        src = service.set_develop({"Exposure2012": base + 0.3, "Contrast2012": starts[first]["Contrast2012"] + 10}, reason="acceptance reuse", photo=first)
        plan = service.batch_plan_from_edit(src["edit_id"], "selected")
        others = [p["id"] for p in photos if p["id"] != first]
        check("plan from edit: nothing changed, source photo excluded", plan["nothing_was_changed"] and plan["will_change"] == len(others)
              and first not in [r["photo_id"] for r in plan["photos"]])
        done = service.batch_apply(plan["plan_id"])
        now = {pid: bridge.call("snapshot", {"photo": pid})["settings"] for pid in others}
        check("the other photos moved by exactly the same relative amount", done["changed"] == len(others)
              and all(abs(now[i]["Exposure2012"] - (starts[i]["Exposure2012"] + 0.3)) < 1e-3 and abs(now[i]["Contrast2012"] - (starts[i]["Contrast2012"] + 10)) < 1e-3 for i in others))
        undone = service.restore(done["batch_id"])
        check("restore of the batch brings them back", not undone["problems"])
        service.restore(src["edit_id"])
    finally:
        try:
            for pid in starts:
                service.restore_original(photo=pid, force=True)
        except Exception as e:  # noqa: BLE001
            print("cleanup:", str(e)[:120])
        for pid, start in starts.items():
            final = bridge.call("snapshot", {"photo": pid})["settings"]
            diff = differences(start, final)
            check(f"FINAL: every setting of {pid[:8]} is back to the start ({len(start)} keys)", not diff, str(diff)[:150])
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
