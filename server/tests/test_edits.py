import asyncio
import json
import re
from pathlib import Path

import pytest

from lightroom_mcp import edits
from lightroom_mcp.bridge import BridgeError
from lightroom_mcp.edits import EditError, EditService, EditStore, ReadOnlyError, validate_changes

LIMITS_LUA = Path(__file__).resolve().parents[2] / "plugin" / "lrmcp.lrdevplugin" / "Limits.lua"


# ---- a tiny stand-in for the plug-in: same contract and same checks as Commands.lua -----------------------------
class FakeLightroom:
    def __init__(self):
        self.photos = {
            "AAAAAAAA-1111": {"name": "one.ARW", "wb": "As Shot", "values": {k: 0.0 for k in edits.LIMITS}},
            "BBBBBBBB-2222": {"name": "two.JPG", "wb": "As Shot", "values": {k: 0.0 for k in edits.LIMITS}},
        }
        self.active = "AAAAAAAA-1111"
        self.write_calls = 0
        self.fail_next_write = False
        self.seen_edit_file_before_write = None
        self.store = None

    def _photo(self, ref):
        pid = self.active if ref == "selected" else ref
        if pid not in self.photos:
            raise BridgeError("在当前目录里找不到这张照片")
        return pid, self.photos[pid]

    def __call__(self, command, params=None, timeout=30.0):
        params = params or {}
        if command == "list_selected":
            return {"active_id": self.active, "count": 1, "photos": []}
        if command == "get_develop":
            pid, p = self._photo(params["photo"])
            v = p["values"]
            hsl = {c: {"hue": v["HueAdjustment" + c], "saturation": v["SaturationAdjustment" + c],
                       "luminance": v["LuminanceAdjustment" + c]} for c in edits.COLORS}
            settings = {k: x for k, x in v.items() if not k.startswith(edits.HSL_PREFIXES)}
            settings["WhiteBalance"] = p["wb"]
            return {"photo": {"id": pid, "name": p["name"]}, "settings": settings, "hsl": hsl}
        if command == "set_develop":
            return self._set(params)
        raise AssertionError(f"unexpected command {command}")

    def _set(self, params):
        self.write_calls += 1
        if self.store is not None:
            self.seen_edit_file_before_write = any(self.store.directory.glob("*.json"))
        if self.fail_next_write:
            self.fail_next_write = False
            raise BridgeError("Lightroom 现在不能写入")
        restoring = params.get("restore") == "1"
        pid, p = self._photo(params["photo"])
        changes = {}
        for k, text in params.items():
            if k in ("photo", "edit", "restore", "wb"):
                continue
            if k not in edits.LIMITS:
                raise BridgeError(f"不允许修改这个参数：{k}")
            low, high, step = edits.LIMITS[k]
            x = float(text)
            if not low <= x <= high:
                raise BridgeError(f"{k} 的取值范围是 {low:g} 到 {high:g}")
            if not restoring and abs(x - p["values"][k]) > step + 1e-9:
                raise BridgeError(f"{k} 单次最多改 ±{step:g}")
            changes[k] = x
        before = {k: p["values"][k] for k in changes}
        p["values"].update(changes)
        reply = {"before": before, "after": dict(changes), "verified": True}
        if any(k in edits.WB_KEYS for k in changes):
            reply["before_wb"] = p["wb"]
            p["wb"] = params["wb"].replace("_", " ") if restoring and "wb" in params else "Custom"
        return reply


@pytest.fixture
def env(tmp_path):
    lr = FakeLightroom()
    store = EditStore(tmp_path / "edits")
    lr.store = store
    service = EditService(lr, store, readonly_file=tmp_path / "readonly")
    return lr, store, service, tmp_path


# ---- validation ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [None, {}, [], "Exposure2012"])
def test_changes_must_be_a_non_empty_dict(bad):
    with pytest.raises(EditError):
        validate_changes(bad)


def test_unknown_and_forbidden_keys_are_refused_with_the_allowed_list():
    for key in ("Sharpness", "ToneCurvePV2012", "CropLeft", "WhiteBalance", "exposure", "../x"):
        with pytest.raises(EditError) as err:
            validate_changes({key: 1})
        assert "不允许修改" in str(err.value) and "Exposure2012" in str(err.value)


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), [1]])
def test_values_must_be_finite_numbers(value):
    with pytest.raises(EditError):
        validate_changes({"Exposure2012": value})


def test_range_is_enforced_at_both_ends():
    assert validate_changes({"Exposure2012": 5, "Contrast2012": -100}) == {"Exposure2012": 5.0, "Contrast2012": -100.0}
    for bad in ({"Exposure2012": 5.01}, {"Exposure2012": -6}, {"Contrast2012": 100.5}, {"HueAdjustmentRed": -101}):
        with pytest.raises(EditError, match="取值范围"):
            validate_changes(bad)


def test_too_many_keys():
    many = {k: 0 for k in list(edits.LIMITS)[:31]}
    assert len(many) == 31
    with pytest.raises(EditError, match="最多改 30"):
        validate_changes(many)


def test_python_and_lua_whitelists_are_identical():
    """Limits.lua is what the plug-in enforces; edits.py is what the server enforces. They must agree exactly."""
    pattern = re.compile(r"^\s*(\w+)\s*=\s*\{\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*([\d.]+)\s*\}\s*,?\s*$")
    lua = {}
    for line in LIMITS_LUA.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            lua[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
    assert lua == edits.LIMITS
    assert len(lua) == 37


# ---- set_develop -----------------------------------------------------------------------------------------------
def test_set_develop_changes_the_photo_and_reports_before_and_after(env):
    lr, store, service, _ = env
    out = service.set_develop({"Exposure2012": 0.3, "Highlights2012": -20}, reason="暗部太暗")
    assert out["verified"] is True and out["photo"] == "one.ARW"
    rows = {r["parameter"]: r for r in out["changes"]}
    assert rows["Exposure2012"]["before"] == 0 and rows["Exposure2012"]["after"] == 0.3 and rows["Exposure2012"]["ok"]
    assert lr.photos["AAAAAAAA-1111"]["values"]["Highlights2012"] == -20
    saved = store.load(out["edit_id"])
    assert saved["status"] == "applied" and saved["reason"] == "暗部太暗" and saved["before"]["Highlights2012"] == 0


def test_old_values_are_on_disk_before_anything_is_written(env):
    lr, store, service, _ = env
    service.set_develop({"Exposure2012": 0.5})
    assert lr.seen_edit_file_before_write is True


def test_a_failed_write_is_recorded_and_changes_nothing(env):
    lr, store, service, _ = env
    lr.fail_next_write = True
    with pytest.raises(BridgeError):
        service.set_develop({"Exposure2012": 0.5})
    (record,) = store.all()
    assert record["status"] == "failed" and record["before"] == {"Exposure2012": 0.0}
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 0


def test_step_limit_is_refused_and_the_photo_is_untouched(env):
    lr, store, service, _ = env
    with pytest.raises(BridgeError, match="单次最多改"):
        service.set_develop({"Exposure2012": 2.0})
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 0
    assert store.all()[0]["status"] == "failed"


def test_selected_photo_is_resolved_once(env):
    lr, store, service, _ = env
    out = service.set_develop({"Exposure2012": 0.2}, photo="selected")
    lr.active = "BBBBBBBB-2222"  # the user clicks another photo afterwards
    service.restore(out["edit_id"])  # must still restore the first photo
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 0
    assert lr.photos["BBBBBBBB-2222"]["values"]["Exposure2012"] == 0


# ---- restore ---------------------------------------------------------------------------------------------------
def test_restore_writes_the_old_values_back_exactly(env):
    lr, store, service, _ = env
    first = service.set_develop({"Exposure2012": 0.7, "Saturation": 20})
    out = service.restore(first["edit_id"])
    v = lr.photos["AAAAAAAA-1111"]["values"]
    assert v["Exposure2012"] == 0 and v["Saturation"] == 0 and out["verified"]
    assert store.load(first["edit_id"])["restored_by"] == out["edit_id"]
    assert store.load(out["edit_id"])["kind"] == "restore"


def test_restoring_twice_does_nothing_the_second_time(env):
    lr, store, service, _ = env
    first = service.set_develop({"Exposure2012": 0.7})
    service.restore(first["edit_id"])
    calls = lr.write_calls
    again = service.restore(first["edit_id"])
    assert "已经" in again["note"] and lr.write_calls == calls


def test_a_restore_record_cannot_be_restored_and_a_failed_edit_needs_none(env):
    lr, store, service, _ = env
    first = service.set_develop({"Exposure2012": 0.7})
    restore_id = service.restore(first["edit_id"])["edit_id"]
    with pytest.raises(EditError, match="本身是一次还原"):
        service.restore(restore_id)
    lr.fail_next_write = True
    with pytest.raises(BridgeError):
        service.set_develop({"Exposure2012": 0.3})
    failed = [r for r in store.all() if r["status"] == "failed"][0]
    with pytest.raises(EditError, match="不需要还原"):
        service.restore(failed["edit_id"])


def test_restore_original_goes_back_to_the_very_first_values(env):
    lr, store, service, _ = env
    service.set_develop({"Exposure2012": 0.8})
    service.set_develop({"Exposure2012": 1.5, "Contrast2012": 25})  # step from 0.8 is 0.7: allowed
    service.set_develop({"Exposure2012": 1.0})
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 1.0
    dry = service.restore_original(dry_run=True)
    assert dry["dry_run"] is True and dry["will_write"] == {"Exposure2012": 0.0, "Contrast2012": 0.0}
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 1.0  # the dry run wrote nothing
    out = service.restore_original()
    v = lr.photos["AAAAAAAA-1111"]["values"]
    assert v["Exposure2012"] == 0 and v["Contrast2012"] == 0 and out["verified"]
    assert len(out["edits_undone"]) == 3
    assert "无需还原" in service.restore_original()["note"]


def test_restore_original_only_touches_the_chosen_photo(env):
    lr, store, service, _ = env
    service.set_develop({"Exposure2012": 0.5}, photo="AAAAAAAA-1111")
    service.set_develop({"Exposure2012": 0.4}, photo="BBBBBBBB-2222")
    service.restore_original(photo="AAAAAAAA-1111")
    assert lr.photos["AAAAAAAA-1111"]["values"]["Exposure2012"] == 0
    assert lr.photos["BBBBBBBB-2222"]["values"]["Exposure2012"] == 0.4


# ---- read-only switch ------------------------------------------------------------------------------------------
def test_read_only_file_refuses_every_write_without_calling_the_plugin(env):
    lr, store, service, tmp = env
    first = service.set_develop({"Exposure2012": 0.5})
    (tmp / "readonly").write_text("1")
    calls = lr.write_calls
    with pytest.raises(ReadOnlyError, match="只读模式"):
        service.set_develop({"Exposure2012": 0.6})
    with pytest.raises(ReadOnlyError):
        service.restore(first["edit_id"])
    with pytest.raises(ReadOnlyError):
        service.restore_original()
    assert lr.write_calls == calls
    assert service.restore_original(dry_run=True)["dry_run"]  # looking is still allowed
    assert service.list_edits()["count"] == 1


def test_read_only_environment_variable(env, monkeypatch):
    lr, store, service, _ = env
    monkeypatch.setenv("LRMCP_READONLY", "1")
    with pytest.raises(ReadOnlyError):
        service.set_develop({"Exposure2012": 0.1})
    assert lr.write_calls == 0


# ---- records ---------------------------------------------------------------------------------------------------
def test_list_edits_newest_first_and_filtered(env):
    lr, store, service, _ = env
    a = service.set_develop({"Exposure2012": 0.1}, photo="AAAAAAAA-1111")
    b = service.set_develop({"Exposure2012": 0.2}, photo="BBBBBBBB-2222")
    everything = service.list_edits()
    assert [e["edit_id"] for e in everything["edits"]] == [b["edit_id"], a["edit_id"]]
    only_a = service.list_edits(photo="AAAAAAAA-1111")
    assert [e["edit_id"] for e in only_a["edits"]] == [a["edit_id"]]
    assert service.list_edits(photo="selected")["count"] == 1


def test_edit_ids_cannot_escape_the_edit_folder(env):
    _, store, service, _ = env
    for bad in ("../../secret", "..\\x", "20261102-120000-zzzz", "", "a/b"):
        with pytest.raises(EditError):
            store.load(bad)


# ---- the MCP tools ---------------------------------------------------------------------------------------------
def test_tools_are_registered_with_the_right_hints():
    from lightroom_mcp.tools import build_server

    tools = asyncio.run(build_server(None, "x").list_tools())
    hints = {t.name: t.annotations.read_only_hint for t in tools}
    assert hints == {
        "lr_status": True, "lr_list_selected": True, "lr_get_develop": True, "lr_get_preview": True, "lr_doctor": True,
        "lr_set_develop": False, "lr_restore": False, "lr_restore_original": False, "lr_list_edits": True,
    }
    set_tool = next(t for t in tools if t.name == "lr_set_develop")
    assert "Exposure2012" in set_tool.description and "单次最多改" in set_tool.description
    assert json.dumps(set_tool.input_schema)  # the schema can be serialised


# ---- white balance (Temperature / Tint) -----------------------------------------------------------------------
def test_white_balance_change_sets_custom_and_restore_brings_the_label_back(env):
    lr, store, service, _ = env
    lr.photos["AAAAAAAA-1111"]["values"].update(Temperature=5600.0, Tint=13.0)
    result = service.set_develop({"Temperature": 6400, "Tint": 20}, reason="warmer")
    assert result["verified"] and lr.photos["AAAAAAAA-1111"]["wb"] == "Custom"
    assert store.load(result["edit_id"])["before_wb"] == "As Shot"
    service.restore(result["edit_id"])
    photo = lr.photos["AAAAAAAA-1111"]
    assert photo["wb"] == "As Shot" and photo["values"]["Temperature"] == 5600.0 and photo["values"]["Tint"] == 13.0


def test_restore_original_after_two_white_balance_edits_uses_the_first_label(env):
    lr, store, service, _ = env
    lr.photos["AAAAAAAA-1111"]["values"].update(Temperature=5600.0, Tint=13.0)
    service.set_develop({"Temperature": 6400})
    service.set_develop({"Temperature": 7000})
    service.restore_original()
    photo = lr.photos["AAAAAAAA-1111"]
    assert photo["wb"] == "As Shot" and photo["values"]["Temperature"] == 5600.0


def test_white_balance_range_is_checked():
    with pytest.raises(EditError):
        validate_changes({"Temperature": 1500})
    with pytest.raises(EditError):
        validate_changes({"Tint": 151})
    assert validate_changes({"Temperature": 6500, "Tint": -20}) == {"Temperature": 6500.0, "Tint": -20.0}
