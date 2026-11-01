"""v1.1 acceptance check for the WRITE tools against a real Lightroom.

SAFETY: runs only when the open catalog's path contains "ceshi" (the test catalog) and exactly one photo is selected.
Every change is undone at the end (restore_original) and the script then compares ALL values that get_develop reports
with the state it started from, and the preview file size (pixel identity) with the baseline.
It uses its own temporary edit folder, so your real ~/LrMcp/edits records are not touched.

Stop any other lrmcp server on port 58770 first. Usage: python acceptance_write.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp import config, edits  # noqa: E402
from lightroom_mcp.bridge import Bridge, BridgeBusy, BridgeError  # noqa: E402
from lightroom_mcp.edits import EditError, EditService, EditStore, ReadOnlyError  # noqa: E402

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")


def preview_size(bridge: Bridge, photo_id: str) -> int:
    data = bridge.call("get_preview", {"photo": photo_id, "long_edge": 1024}, timeout=60)
    return Path(data["path"]).stat().st_size


def everything(develop: dict) -> dict:
    """All values get_develop reports, flattened, to compare before/after."""
    flat = dict(develop["settings"])
    for color, row in develop["hsl"].items():
        for field, value in row.items():
            flat[f"hsl.{color}.{field}"] = value
    return flat


def main() -> int:
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 2
    store_dir = Path(tempfile.mkdtemp(prefix="lrmcp-acceptance-"))
    service = EditService(bridge.call, EditStore(store_dir), readonly_file=store_dir / "readonly")
    readonly_flag = config.DATA_DIR / "readonly"  # the file the PLUG-IN checks
    photo_id = None
    try:
        if not bridge.wait_connected(40):
            print("plug-in did not connect")
            return 2
        status = bridge.call("status")
        if "ceshi" not in status["catalog_path"]:
            print(f"REFUSED: the open catalog is not the test catalog: {status['catalog_path']}")
            return 2
        listing = bridge.call("list_selected")
        if listing["count"] != 1:
            print(f"REFUSED: select exactly one photo (count={listing['count']})")
            return 2
        if readonly_flag.exists():
            print(f"REFUSED: {readonly_flag} exists; remove it first")
            return 2
        photo = listing["photos"][0]
        photo_id = photo["id"]
        print(f"photo: {photo['name']} ({photo['format']})\n")

        baseline_develop = bridge.call("get_develop", {"photo": photo_id})
        baseline = everything(baseline_develop)
        baseline_size = preview_size(bridge, photo_id)
        base = edits.current_values(baseline_develop, edits.LIMITS)
        check("baseline read: all 35 writable sliders found", len(base) == 35)

        # 1. a normal change
        e1 = service.set_develop({"Exposure2012": base["Exposure2012"] + 0.3, "Vibrance": base["Vibrance"] + 10}, reason="acceptance")
        check("set_develop: verified by read-back", e1["verified"] and all(r["ok"] for r in e1["changes"]))
        after1 = edits.current_values(bridge.call("get_develop", {"photo": photo_id}), ["Exposure2012", "Vibrance"])
        check("set_develop: Lightroom really holds the new values",
              abs(after1["Exposure2012"] - (base["Exposure2012"] + 0.3)) < 1e-3 and abs(after1["Vibrance"] - (base["Vibrance"] + 10)) < 1e-3)
        check("preview changed after the edit", preview_size(bridge, photo_id) != baseline_size)

        # 2. protections (the plug-in must refuse by itself, so call it directly too)
        try:
            service.set_develop({"Exposure2012": base["Exposure2012"] + 0.3 + 1.5})
            check("step limit refuses a +1.5 EV jump", False, "no error")
        except BridgeError as e:
            check("step limit refuses a +1.5 EV jump", "单次最多改" in str(e), str(e)[:60])
        try:
            service.set_develop({"Exposure2012": 9})
            check("range refused by the server", False)
        except EditError as e:
            check("range refused by the server", "取值范围" in str(e))
        for label, params, needle in (
            ("range refused by the plug-in itself", {"Exposure2012": "9"}, "取值范围"),
            ("white balance refused by the plug-in itself", {"Temperature": "6500"}, "不允许修改"),
            ("unknown key refused by the plug-in itself", {"Sharpness": "10"}, "不允许修改"),
        ):
            try:
                bridge.call("set_develop", {"photo": photo_id, "edit": "acceptance", **params})
                check(label, False, "no error")
            except BridgeError as e:
                check(label, needle in str(e), str(e)[:60])
        still = edits.current_values(bridge.call("get_develop", {"photo": photo_id}), ["Exposure2012"])
        check("refused changes changed nothing", abs(still["Exposure2012"] - (base["Exposure2012"] + 0.3)) < 1e-3)

        # 3. HSL
        e2 = service.set_develop({"HueAdjustmentRed": base["HueAdjustmentRed"] + 10, "SaturationAdjustmentBlue": base["SaturationAdjustmentBlue"] - 15,
                                  "LuminanceAdjustmentGreen": base["LuminanceAdjustmentGreen"] + 5}, reason="acceptance hsl")
        check("HSL change verified", e2["verified"])

        # 4. restore one edit: only that edit's sliders go back
        r1 = service.restore(e1["edit_id"])
        now = edits.current_values(bridge.call("get_develop", {"photo": photo_id}), edits.LIMITS)
        check("restore(edit 1) puts Exposure and Vibrance back", r1["verified"] and abs(now["Exposure2012"] - base["Exposure2012"]) < 1e-3
              and abs(now["Vibrance"] - base["Vibrance"]) < 1e-3)
        check("restore(edit 1) leaves the HSL edit alone", abs(now["HueAdjustmentRed"] - (base["HueAdjustmentRed"] + 10)) < 1e-3)
        check("restoring the same edit again does nothing", "已经" in service.restore(e1["edit_id"])["note"])

        # 5. read-only switch: the plug-in checks its own flag file even if the server is bypassed
        readonly_flag.write_text("1")
        try:
            try:
                service2 = EditService(bridge.call, EditStore(store_dir), readonly_file=readonly_flag)
                service2.set_develop({"Exposure2012": base["Exposure2012"] + 0.1})
                check("read-only: server refuses", False)
            except ReadOnlyError:
                check("read-only: server refuses", True)
            try:
                bridge.call("set_develop", {"photo": photo_id, "edit": "acceptance", "Exposure2012": "0.1"})
                check("read-only: plug-in refuses by itself", False, "no error")
            except BridgeError as e:
                check("read-only: plug-in refuses by itself", "只读模式" in str(e))
        finally:
            readonly_flag.unlink(missing_ok=True)

        # 6. history of edits
        listed = service.list_edits(photo=photo_id)
        check("list_edits shows 3 records (2 edits + 1 restore)", listed["count"] >= 3, f"count={listed['count']}")

        # 7. back to the very start
        original = service.restore_original(photo=photo_id)
        check("restore_original verified", original["verified"], f"undid {len(original['edits_undone'])} edit(s)")
    finally:
        readonly_flag.unlink(missing_ok=True)
        if photo_id:
            try:  # whatever happened above, put the test photo back
                service.restore_original(photo=photo_id)
            except Exception as e:  # noqa: BLE001
                print("cleanup:", e)

    final_develop = bridge.call("get_develop", {"photo": photo_id})
    final = everything(final_develop)
    diffs = {k: (baseline.get(k), final.get(k)) for k in set(baseline) | set(final)
             if not (isinstance(baseline.get(k), (int, float)) and isinstance(final.get(k), (int, float)) and abs(baseline[k] - final[k]) < 1e-6)
             and baseline.get(k) != final.get(k)}
    check(f"EVERY value get_develop reports is back to the start ({len(baseline)} values)", not diffs, str(diffs)[:200])
    final_size = preview_size(bridge, photo_id)
    check("preview file size equals the baseline (pixel-identical)", final_size == baseline_size, f"{final_size} vs {baseline_size}")
    bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
