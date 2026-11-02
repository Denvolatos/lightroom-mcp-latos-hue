"""0.10 acceptance check: BATCH changes against a REAL Lightroom (test catalog only).

SAFETY: only on the test catalog (path contains "ceshi") with 2 to 4 photos selected (at least one RAW and one JPEG
makes the white balance skip visible). Everything is undone at the end and the WHOLE settings snapshot of every photo is
compared with the start (keys that did not exist at the start are internal values and are not counted).
The plug-in must be loaded. Usage: python acceptance_batch.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    store_dir = Path(tempfile.mkdtemp(prefix="lrmcp-batch-"))
    service = EditService(bridge.call, EditStore(store_dir), readonly_file=store_dir / "ro")
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
        for p in photos:
            starts[p["id"]] = bridge.call("snapshot", {"photo": p["id"]})["settings"]
        names = {p["id"]: p["name"] for p in photos}
        print("photos: " + ", ".join(f"{p['name']} ({p['format']})" for p in photos) + "\n")

        # 1. dry run changes nothing
        before_exposure = {pid: s["Exposure2012"] for pid, s in starts.items()}
        plan = service.batch_plan({"Exposure2012": 0.3, "Contrast2012": 10}, "selected", reason="acceptance batch")
        check("dry run: every selected photo is in the plan", plan["will_change"] == len(photos) and plan["plan_id"], f"{plan['will_change']} photos")
        now = {p["id"]: bridge.call("snapshot", {"photo": p["id"]})["settings"] for p in photos}
        check("dry run changed nothing", all(not differences(starts[i], now[i]) for i in starts))

        # 2. execute
        done = service.batch_apply(plan["plan_id"])
        check("batch applied to every photo and verified", done["changed"] == len(photos) and all(r.get("verified") for r in done["results"]))
        now = {p["id"]: bridge.call("snapshot", {"photo": p["id"]})["settings"] for p in photos}
        check("each photo moved by exactly the relative amount (exposure +0.3, contrast +10)",
              all(abs(now[i]["Exposure2012"] - (starts[i]["Exposure2012"] + 0.3)) < 1e-3 and abs(now[i]["Contrast2012"] - (starts[i]["Contrast2012"] + 10)) < 1e-3
                  for i in starts))
        try:
            service.batch_apply(plan["plan_id"])
            check("the plan cannot be used twice", False, "no error")
        except EditError:
            check("the plan cannot be used twice", True)

        # 3. one restore undoes the whole batch
        undone = service.restore(done["batch_id"])
        now = {p["id"]: bridge.call("snapshot", {"photo": p["id"]})["settings"] for p in photos}
        check("lr_restore(batch_id) undoes every photo", not undone["problems"] and all(not differences(starts[i], now[i]) for i in starts))

        # 4. white balance: RAW photos can, JPEG photos are skipped with a reason
        raws = [p for p in photos if p["format"] == "RAW"]
        jpgs = [p for p in photos if p["format"] != "RAW"]
        wb = service.batch_plan({"Temperature": 200}, "selected")
        by_id = {r["photo_id"]: r for r in wb["photos"]}
        check("white balance batch: RAW photos are planned", all(by_id[p["id"]]["will_change"] for p in raws))
        if jpgs:
            check("white balance batch: JPEG photos are skipped with a reason", all(not by_id[p["id"]]["will_change"] and "JPEG" in by_id[p["id"]]["reason_skipped"] for p in jpgs))
        if wb["plan_id"]:
            wdone = service.batch_apply(wb["plan_id"])
            service.restore(wdone["batch_id"])

        # 5. refusals
        for label, changes in (("crop is refused in a batch", {"CropLeft": 0.1}), ("a too big step is refused", {"Exposure2012": 2.0})):
            try:
                service.batch_plan(changes, "selected")
                check(label, False, "no error")
            except EditError:
                check(label, True)
        _ = names, before_exposure
    finally:
        for pid in starts:
            try:
                service.restore_original(photo=pid)
            except Exception as e:  # noqa: BLE001
                print("cleanup:", str(e)[:100])
        for pid, start in starts.items():
            final = bridge.call("snapshot", {"photo": pid})["settings"]
            diff = differences(start, final)
            check(f"FINAL: every setting of {pid[:8]} is back to the start ({len(start)} keys)", not diff, str(diff)[:150])
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
