# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""0.3.0 acceptance check: SEVERAL servers (= several AI sessions) against one real Lightroom.

SAFETY: only on the test catalog (path contains "ceshi") with exactly one photo selected. All changes are undone at the
end and ALL values get_develop reports are compared with the state at the start. Uses temporary edit folders.
The plug-in (0.3.0) must have been reloaded in Lightroom. Usage: python acceptance_multi.py
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp import edits  # noqa: E402
from lightroom_mcp.bridge import Bridge, BridgeBusy  # noqa: E402
from lightroom_mcp.edits import EditService, EditStore  # noqa: E402

failures = 0


def check(label, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")


def everything(develop):
    flat = dict(develop["settings"])
    for color, row in develop["hsl"].items():
        for field, value in row.items():
            flat[f"hsl.{color}.{field}"] = value
    return flat


def run_threads(jobs):
    """jobs: list of callables; returns (results, errors) in the same order."""
    results, errors = [None] * len(jobs), [None] * len(jobs)

    def wrap(i, job):
        try:
            results[i] = job()
        except Exception as e:  # noqa: BLE001
            errors[i] = e

    threads = [threading.Thread(target=wrap, args=(i, j)) for i, j in enumerate(jobs)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return results, errors, time.time() - t0


def main():
    a, b = Bridge(), Bridge()
    try:
        a.start()
        b.start()
    except BridgeBusy as e:
        print(e)
        return 2
    store_dirs = [Path(tempfile.mkdtemp(prefix="lrmcp-multi-")) for _ in range(2)]
    svc_a = EditService(a.call, EditStore(store_dirs[0]), readonly_file=store_dirs[0] / "ro")
    svc_b = EditService(b.call, EditStore(store_dirs[1]), readonly_file=store_dirs[1] / "ro")
    photo_id, baseline = None, None
    try:
        check("two servers got different ports", a.port != b.port, f"{a.port} and {b.port}")
        t0 = time.time()
        ok_a, ok_b = a.wait_connected(40), b.wait_connected(40)
        check("the plug-in connects to BOTH servers", ok_a and ok_b, f"within {time.time() - t0:.1f}s")
        if not (ok_a and ok_b):
            return 1

        sa, sb = a.call("status"), b.call("status")
        check("both see the same Lightroom, plug-in 0.3.x", sa["plugin_version"].startswith("0.3") and sa["lightroom_version"] == sb["lightroom_version"],
              f"plug-in {sa['plugin_version']}, Lightroom {sa['lightroom_version']}")
        if "ceshi" not in sa["catalog_path"]:
            print(f"REFUSED: not the test catalog: {sa['catalog_path']}")
            return 2
        listing = a.call("list_selected")
        if listing["count"] != 1:
            print(f"REFUSED: select exactly one photo (count={listing['count']})")
            return 2
        photo_id = listing["photos"][0]["id"]
        print(f"photo: {listing['photos'][0]['name']}\n")

        baseline = everything(a.call("get_develop", {"photo": photo_id}))
        base = {k: baseline[k] for k in ("Exposure2012", "Contrast2012")}

        # concurrent reads, from both servers at the same time
        jobs = [lambda: a.call("get_develop", {"photo": photo_id}) for _ in range(8)] + \
               [lambda: b.call("list_selected") for _ in range(8)] + \
               [lambda: a.call("get_preview", {"photo": photo_id, "long_edge": 512}, timeout=90),
                lambda: b.call("get_preview", {"photo": photo_id, "long_edge": 512}, timeout=90)]
        results, errors, secs = run_threads(jobs)
        check("20 concurrent calls from two servers all succeed", not any(errors), f"{secs:.1f}s; errors: {[str(e) for e in errors if e][:2]}")
        check("both previews exist and are different files", results[-1]["path"] != results[-2]["path"] and Path(results[-1]["path"]).is_file()
              and Path(results[-2]["path"]).is_file())

        # concurrent writes to the same photo, different sliders, from two servers
        results, errors, secs = run_threads([
            lambda: svc_a.set_develop({"Exposure2012": base["Exposure2012"] + 0.4}, reason="multi A", photo=photo_id),
            lambda: svc_b.set_develop({"Contrast2012": base["Contrast2012"] + 15}, reason="multi B", photo=photo_id),
        ])
        check("two simultaneous changes from two servers both apply and verify", not any(errors) and all(r["verified"] for r in results),
              f"{secs:.1f}s; errors: {[str(e) for e in errors if e]}")
        now = edits.current_values(a.call("get_develop", {"photo": photo_id}), ["Exposure2012", "Contrast2012"])
        check("Lightroom holds BOTH changes", abs(now["Exposure2012"] - (base["Exposure2012"] + 0.4)) < 1e-3 and abs(now["Contrast2012"] - (base["Contrast2012"] + 15)) < 1e-3)

        # one server goes away: the other must keep working, and the plug-in must drop the dead one
        b.stop()
        time.sleep(4)
        check("the remaining server still works after the other one stopped", a.call("status")["plugin_version"] == sa["plugin_version"])
        check("the stopped server's announcement is gone", not (a.data_dir / "servers" / f"{b.port}.txt").exists())
        b = Bridge()  # a new session starts later
        b.start()
        t1 = time.time()
        check("a server started later is discovered too", b.wait_connected(40), f"{time.time() - t1:.1f}s")
        svc_b = EditService(b.call, EditStore(store_dirs[1]), readonly_file=store_dirs[1] / "ro")
    finally:
        # put the test photo back, whatever happened
        if photo_id:
            for svc in (svc_a, svc_b):
                try:
                    svc.restore_original(photo=photo_id)
                except Exception as e:  # noqa: BLE001
                    print("cleanup:", str(e)[:100])
        if baseline is not None:
            final = everything(a.call("get_develop", {"photo": photo_id}))
            diffs = {k: (baseline.get(k), final.get(k)) for k in set(baseline) | set(final)
                     if baseline.get(k) != final.get(k) and not (isinstance(baseline.get(k), (int, float)) and isinstance(final.get(k), (int, float)) and abs(baseline[k] - final[k]) < 1e-6)}
            check(f"EVERY value get_develop reports is back to the start ({len(baseline)} values)", not diffs, str(diffs)[:200])
        a.stop()
        b.stop()
    left = {f.stem for f in (a.data_dir / "servers").glob("*.txt")} & {str(a.port), str(b.port)}
    check("this script's own announcement files were removed", not left, str(left))
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
