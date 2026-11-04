# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""0.11 acceptance check: catalog information (rating, flag, colour label, title, caption, keywords) against a REAL
Lightroom (test catalog only).

SAFETY: only on the test catalog (path contains "ceshi") with exactly one photo selected. Everything is undone at the end
and the metadata is compared with the start. The one thing that stays: a keyword created by this test remains in the test
catalog's keyword list (the SDK cannot delete keywords); it is removed from the photo.
The plug-in (0.11.x) must have been reloaded. Usage: python acceptance_metadata.py
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


def norm(meta):
    out = dict(meta)
    out["color_label"] = str(out.get("color_label", "none")).lower()
    out["keywords"] = sorted(out.get("keywords", []))
    return out


def main():
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 2
    store_dir = Path(tempfile.mkdtemp(prefix="lrmcp-meta-"))
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

        start = norm(service.get_metadata(photo_id)["metadata"])
        print(f"start: {start}\n")
        check("get_metadata returns all fields", set(start) == {"rating", "flag", "color_label", "title", "caption", "keywords"})

        word = "lrmcp-test-keyword"
        title = "Tramonto à Torino, prova 中文"
        e1 = service.set_metadata(rating=4, flag="pick", color_label="green", title=title, caption="Una didascalia, con virgola & spazi",
                                  add_keywords=[word, "sera lrmcp"], reason="acceptance")
        now = norm(service.get_metadata(photo_id)["metadata"])
        check("everything was written and read back", e1["verified"] and now["rating"] == 4 and now["flag"] == "pick" and now["color_label"] == "green"
              and now["title"] == title and now["caption"] == "Una didascalia, con virgola & spazi" and word in now["keywords"] and "sera lrmcp" in now["keywords"])

        e2 = service.set_metadata(rating=0, flag="reject", color_label="none", title="", remove_keywords=[word])
        now = norm(service.get_metadata(photo_id)["metadata"])
        check("rating 0, reject, no colour, empty title and keyword removal", e2["verified"] and now["rating"] == 0 and now["flag"] == "reject"
              and now["color_label"] == "none" and now["title"] == "" and word not in now["keywords"])

        service.restore(e2["edit_id"])
        now = norm(service.get_metadata(photo_id)["metadata"])
        check("restore of the second change brings the first state back", now["rating"] == 4 and now["flag"] == "pick" and now["color_label"] == "green"
              and now["title"] == title and word in now["keywords"])
        service.restore(e1["edit_id"])
        now = norm(service.get_metadata(photo_id)["metadata"])
        check("restore of the first change brings back the START", now == start, str({k: (start[k], now[k]) for k in start if start[k] != now[k]}))

        for label, kwargs in (("rating 9 is refused", dict(rating=9)), ("a keyword with a comma is refused", dict(add_keywords=["a,b"]))):
            try:
                service.set_metadata(**kwargs)
                check(label, False, "no error")
            except EditError:
                check(label, True)
        check("refused changes changed nothing", norm(service.get_metadata(photo_id)["metadata"]) == start)
    finally:
        if photo_id and start is not None:
            for record in reversed(service.store.all()):
                if record.get("kind") == "meta" and record.get("status") == "applied" and not record.get("restored_by"):
                    try:
                        service.restore(record["edit_id"])
                    except Exception as e:  # noqa: BLE001
                        print("cleanup:", str(e)[:100])
            final = norm(service.get_metadata(photo_id)["metadata"])
            check("FINAL: catalog information is back to the start", final == start, str({k: (start[k], final[k]) for k in start if start[k] != final[k]}))
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
