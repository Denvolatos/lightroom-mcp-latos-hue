"""0.13 acceptance check: EXPORT, named VERSIONS, side-by-side COMPARE and region analysis against a REAL Lightroom (test catalog).

SAFETY: only on the test catalog (path contains "ceshi") with exactly one photo selected. Exports go to ~/LrMcp/exports and to a
throw-away folder this script makes and removes; the files it creates are deleted at the end (only those). All develop changes are
undone and the whole settings snapshot is compared with the start. Do not click in Lightroom while this runs.
The plug-in (0.13.x) must have been reloaded. Usage: python acceptance_export_versions.py
"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightroom_mcp import tools  # noqa: E402
from lightroom_mcp.bridge import Bridge, BridgeBusy, BridgeError  # noqa: E402
from lightroom_mcp.edits import EditError, EditService, EditStore  # noqa: E402
from lightroom_mcp.versions import VersionStore  # noqa: E402

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


def tool(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def main():
    bridge = Bridge()
    try:
        bridge.start()
    except BridgeBusy as e:
        print(e)
        return 2
    work = Path(tempfile.mkdtemp(prefix="lrmcp-ev-"))
    store = EditStore(work / "edits")
    versions = VersionStore(work / "versions")
    service = EditService(bridge.call, store, readonly_file=work / "ro", versions=versions)
    made_files: list[Path] = []
    export_dir = Path.home() / "lrmcp_acceptance_export"      # no "AppData", no "/lrmcp/" segment: allowed by the plug-in
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
        photo = listing["photos"][0]
        photo_id = photo["id"]
        print(f"photo: {photo['name']} ({photo['format']}), {photo['width']}x{photo['height']}\n")
        start = bridge.call("snapshot", {"photo": photo_id})["settings"]
        tools.EditService = lambda call: EditService(call, store, readonly_file=work / "ro", versions=versions)
        server = tools.build_server(bridge)

        # ---- 1. region analysis in a real preview
        preview = tool(server, "lr_get_preview", {"photo": photo_id, "long_edge": 512})
        stats = json.loads(preview.content[0].text)["stats"]
        check("preview numbers include a 3x3 grid and the sky-like blue", len(stats.get("regions_3x3", [])) == 9 and "sky_like_blue" in stats,
              f"sky: {stats.get('sky_like_blue')}")

        # ---- 2. export: full size and a smaller one to the plug-in's data folder
        full = bridge.call("export_photo", {"photo": photo_id, "destination": "data"}, timeout=300)
        small = bridge.call("export_photo", {"photo": photo_id, "destination": "data", "long_edge": "1024", "quality": "80"}, timeout=300)
        again = bridge.call("export_photo", {"photo": photo_id, "destination": "data"}, timeout=300)
        made_files += [Path(full["path"]), Path(small["path"]), Path(again["path"])]
        with Image.open(full["path"]) as im:
            full_size = im.size
        with Image.open(small["path"]) as im:
            small_size = im.size
        expected = (photo["width"], photo["height"])
        check("full-size export has the photo's own size", full_size == expected or full_size == expected[::-1], f"{full_size} vs {expected}")
        check("a 1024 export is 1024 on the long side and smaller in bytes", max(small_size) == 1024 and Path(small["path"]).stat().st_size < Path(full["path"]).stat().st_size,
              f"{small_size}, {Path(small['path']).stat().st_size} B vs {Path(full['path']).stat().st_size} B")
        check("a second export never overwrites (a new name)", again["path"] != full["path"] and Path(full["path"]).is_file() and "_2" in again["file"], again["file"])
        check("exported files are JPEGs", Path(full["path"]).read_bytes()[:2] == b"\xff\xd8")

        # ---- 3. export into a folder the user named (through the tool), and the refusals
        export_dir.mkdir(exist_ok=True)
        named = json.loads(tool(server, "lr_export", {"photo": photo_id, "folder": str(export_dir), "long_edge": 800}).content[0].text)
        made_files.append(Path(named["path"]))
        check("export into the folder the user named", Path(named["path"]).parent == export_dir and Path(named["path"]).is_file(), named["path"])
        for label, folder in (("a folder that does not exist", str(export_dir / "nope")), ("a system folder", "C:\\Windows\\Temp"),
                              ("a network path", "\\\\server\\share"), ("the tool's own data folder", str(Path.home() / "LrMcp" / "previews"))):
            try:
                if folder.startswith("\\\\"):
                    bridge.call("export_photo", {"photo": photo_id, "folder": folder.replace("\\", "%5C")}, timeout=60)   # past the server check
                else:
                    tool(server, "lr_export", {"photo": photo_id, "folder": folder, "long_edge": 800})
                check(f"export refused: {label}", False, "no error")
            except Exception as e:  # noqa: BLE001 - ToolError or BridgeError
                check(f"export refused: {label}", True, str(e)[:70])
        try:
            bridge.call("export_photo", {"photo": photo_id}, timeout=60)
            check("export without any place is refused by the plug-in", False, "no error")
        except BridgeError as e:
            check("export without any place is refused by the plug-in", "请让用户说清楚" in str(e))

        # ---- 4. named versions: save, change, save, go back, compare, undo
        base_exp, base_con = start["Exposure2012"], start["Contrast2012"]
        v1 = json.loads(tool(server, "lr_save_version", {"name": "start", "note": "as found", "photo": photo_id}).content[0].text)
        check("version saved with a real preview picture", v1["has_preview_picture"] and v1["saved_settings"] > 80, f"{v1['saved_settings']} settings")
        service.set_develop({"Exposure2012": base_exp + 0.6, "Contrast2012": base_con + 25}, photo=photo_id)
        service.set_develop({"Contrast2012": base_con + 50}, photo=photo_id)
        tool(server, "lr_save_version", {"name": "bold", "photo": photo_id})
        service.set_develop({"Exposure2012": base_exp, "Contrast2012": base_con + 25}, photo=photo_id)
        service.set_develop({"Contrast2012": base_con}, photo=photo_id)
        back = json.loads(tool(server, "lr_apply_version", {"name": "bold", "photo": photo_id}).content[0].text)
        now = bridge.call("get_develop", {"photo": photo_id})["settings"]
        check("apply_version goes to 'bold' in ONE change (contrast +50 is beyond the per-call limit)", back["verified"]
              and abs(now["Exposure2012"] - (base_exp + 0.6)) < 1e-3 and abs(now["Contrast2012"] - (base_con + 50)) < 1e-3, f"{back['settings_changed']} settings")
        compared = tool(server, "lr_compare", {"photo": photo_id})
        legend = json.loads(compared.content[0].text)["legend"]
        check("lr_compare gives ONE picture with letters for the current look and both versions",
              [c.type for c in compared.content] == ["text", "image"] and [e["label"] for e in legend] == ["A", "B", "C"])
        check("the numbers differ between 'start' and 'bold'", abs(legend[2]["stats"]["mean_brightness_0_255"] - legend[1]["stats"]["mean_brightness_0_255"]) > 0.3
              or abs(legend[2]["stats"]["warm_cool_index_percent"] - legend[1]["stats"]["warm_cool_index_percent"]) > 0.1)
        service.restore(back["edit_id"])
        now = bridge.call("get_develop", {"photo": photo_id})["settings"]
        check("lr_restore undoes the switch", abs(now["Exposure2012"] - base_exp) < 1e-3 and abs(now["Contrast2012"] - base_con) < 1e-3)
        to_start = json.loads(tool(server, "lr_apply_version", {"name": "start", "photo": photo_id}).content[0].text)
        check("applying a version the photo already has changes nothing", to_start["settings_changed"] == 0)
        tool(server, "lr_delete_version", {"name": "bold", "photo": photo_id})
        check("a deleted version is gone", [v["name"] for v in service.list_versions(photo_id)["versions"]] == ["start"])
        try:
            service.apply_version("no such version", photo=photo_id)
            check("an unknown version name is refused", False, "no error")
        except EditError as e:
            check("an unknown version name is refused", "没有叫" in str(e))
    finally:
        if photo_id and start is not None:
            try:
                service.restore_original(photo=photo_id, force=True)
            except Exception as e:  # noqa: BLE001
                print("cleanup:", str(e)[:120])
            final = bridge.call("snapshot", {"photo": photo_id})["settings"]
            diff = differences(start, final)
            check(f"FINAL: every setting is back to the start ({len(start)} keys)", not diff, str(diff)[:150])
        for f in made_files:                       # remove only the files this run created
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        if export_dir.is_dir() and not any(export_dir.iterdir()):
            export_dir.rmdir()
        shutil.rmtree(work, ignore_errors=True)
        bridge.stop()
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
