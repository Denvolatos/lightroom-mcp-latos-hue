"""Run the plug-in's real Commands.lua (v1.1 write logic) against a fake Lightroom SDK, in a Lua 5.1 interpreter.
Skipped when the optional package ``lupa`` is not installed."""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.lua51")

PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "lrmcp.lrdevplugin"

FAKE_SDK = r"""
local read_plugin_file = ...

-- state the tests can inspect and change
FAKE = { readonly = false, write_gate = "executed", writes = {}, values = {}, uuid = "AAAAAAAA-1111",
         fail_read = nil, round_to = nil }

local function child(a, b) return a .. "\\" .. b end

local photo = {}
function photo:getRawMetadata(key)
  if key == "uuid" then return FAKE.uuid end
  if key == "path" then return "C:\\photos\\one.ARW" end
  if key == "fileFormat" then return "RAW" end
  if key == "dimensions" then return { width = 6000, height = 4000 } end
  if key == "isVideo" then return false end
  if key == "pickStatus" then return 0 end
  return nil
end
function photo:getFormattedMetadata(key) return nil end
function photo:getDevelopSettings()
  local copy = {}
  for k, v in pairs(FAKE.values) do copy[k] = v end
  if FAKE.fail_read then copy[FAKE.fail_read] = nil end
  return copy
end
function photo:applyDevelopSettings(settings, name)
  FAKE.writes[#FAKE.writes + 1] = { settings = settings, name = name }
  for k, v in pairs(settings) do
    FAKE.values[k] = FAKE.round_to and (math.floor(v / FAKE.round_to + 0.5) * FAKE.round_to) or v
  end
end

local catalog = {}
function catalog:getPath() return "C:\\test\\test.lrcat" end
function catalog:getTargetPhoto() return photo end
function catalog:getTargetPhotos() return { photo } end
function catalog:findPhotoByUuid(id) if id == FAKE.uuid then return photo end end
function catalog:withWriteAccessDo(name, fn, params)
  if FAKE.write_gate ~= "executed" then return FAKE.write_gate end
  fn({})
  return "executed"
end

local modules = {
  LrApplication = { activeCatalog = function() return catalog end,
                    versionTable = function() return { major = 15, minor = 2, revision = 0, build_version = "x" } end },
  LrDate = { currentTime = function() return 0 end },
  LrExportSession = function() error("not used in these tests") end,
  LrFileUtils = { exists = function(path) if FAKE.readonly and path:find("readonly", 1, true) then return "file" end return false end,
                  createAllDirectories = function() end, delete = function() end,
                  fileAttributes = function() return {} end },
  LrPathUtils = { child = child, getStandardFilePath = function() return "C:\\Users\\test" end,
                  leafName = function(p) return (p:match("([^\\]+)$")) end },
}
function import(name) return assert(modules[name], "no fake for " .. name) end

local cache = {}
function require(name)
  if cache[name] == nil then
    local chunk, err = loadstring(read_plugin_file(name), "@" .. name)
    assert(chunk, err)
    cache[name] = chunk()
  end
  return cache[name]
end

local Commands = require("Commands.lua")
local Json = require("Json.lua")

-- run a command like Bridge.lua does and return JSON text: {ok=true,data=...} or {ok=false,error=...}
function RUN(command, params)
  local ok, res = pcall(Commands.run, command, params)
  if ok then return Json.encode({ ok = true, data = res }) end
  return Json.encode({ ok = false, error = type(res) == "table" and res.lrmcp or tostring(res) })
end
function SET(key, value) FAKE.values[key] = value end
function RESET()
  FAKE.readonly, FAKE.write_gate, FAKE.writes, FAKE.fail_read, FAKE.round_to = false, "executed", {}, nil, nil
  FAKE.values = { Exposure2012 = 0, Contrast2012 = 0, Saturation = 0, HueAdjustmentRed = 0, Sharpness = 40,
                  WhiteBalance = 'As Shot', Temperature = 5600, Tint = 13 }
end
RESET()
"""


@pytest.fixture
def lr():
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(FAKE_SDK, lambda name: (PLUGIN / name).read_text(encoding="utf-8"))
    g = runtime.globals()

    class Harness:
        def run(self, command, **params):
            table = runtime.table_from({k: str(v) for k, v in params.items()})
            return json.loads(g.RUN(command, table))

        def values(self):
            return {k: v for k, v in g.FAKE["values"].items()}  # ["values"]: .values would be lupa's method

        def writes(self):
            return len(g.FAKE["writes"])

        def set_flag(self, name, value):
            g.FAKE[name] = value

        def reset(self):
            g.RESET()

        def set_value(self, key, value):
            g.SET(key, value)

    h = Harness()
    h.reset()
    return h


def test_a_normal_change_is_written_and_reported(lr):
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="0.3", Contrast2012="10")
    assert reply["ok"] and reply["data"]["verified"] is True
    assert reply["data"]["before"] == {"Exposure2012": 0, "Contrast2012": 0}
    assert reply["data"]["after"] == {"Exposure2012": 0.3, "Contrast2012": 10}
    assert lr.values()["Exposure2012"] == 0.3 and lr.writes() == 1


def test_unknown_parameter_is_refused_before_any_write(lr):
    for key in ("CropLeft", "ToneCurvePV2012", "Sharpness"):
        reply = lr.run("set_develop", photo="selected", edit="e1", **{key: "1"})
        assert not reply["ok"] and "不允许修改" in reply["error"], key
    assert lr.writes() == 0


def test_range_is_checked_in_the_plugin_too(lr):
    for key, value in (("Exposure2012", "5.5"), ("Exposure2012", "-5.1"), ("Contrast2012", "101"), ("HueAdjustmentRed", "-200")):
        reply = lr.run("set_develop", photo="selected", edit="e1", **{key: value})
        assert not reply["ok"] and "取值范围" in reply["error"], (key, value)
    assert lr.writes() == 0


def test_not_a_number_is_refused(lr):
    for bad in ("abc", "", "nan", "inf", "1e999"):
        reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012=bad)
        assert not reply["ok"], bad
    assert lr.writes() == 0


def test_step_limit_blocks_a_big_jump_but_not_a_restore(lr):
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="2.0")
    assert not reply["ok"] and "单次最多改" in reply["error"] and "1" in reply["error"]
    assert lr.values()["Exposure2012"] == 0 and lr.writes() == 0
    lr.set_value("Exposure2012", 4.0)
    restore = lr.run("set_develop", photo="selected", edit="e2", restore="1", Exposure2012="0")
    assert restore["ok"] and lr.values()["Exposure2012"] == 0  # a restore may jump back by more than the step


def test_restore_still_obeys_whitelist_and_range(lr):
    reply = lr.run("set_develop", photo="selected", edit="e1", restore="1", Exposure2012="9")
    assert not reply["ok"] and "取值范围" in reply["error"]
    reply = lr.run("set_develop", photo="selected", edit="e1", restore="1", Sharpness="50")
    assert not reply["ok"] and "不允许修改" in reply["error"]


def test_read_only_flag_file_stops_everything(lr):
    lr.set_flag("readonly", True)
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="0.1")
    assert not reply["ok"] and "只读模式" in reply["error"] and lr.writes() == 0
    restore = lr.run("set_develop", photo="selected", edit="e1", restore="1", Exposure2012="0")
    assert not restore["ok"] and "只读模式" in restore["error"] and lr.writes() == 0


def test_busy_lightroom_means_no_change_and_a_clear_message(lr):
    lr.set_flag("write_gate", "aborted")
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="0.2")
    assert not reply["ok"] and "没有做任何修改" in reply["error"]


def test_unreadable_current_value_cancels_the_change(lr):
    lr.set_flag("fail_read", "Exposure2012")
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="0.2")
    assert not reply["ok"] and "读不到" in reply["error"] and lr.writes() == 0


def test_edit_id_is_required_and_must_be_plain(lr):
    for bad in ({}, {"edit": "a b"}, {"edit": "../x"}, {"edit": ""}):
        reply = lr.run("set_develop", photo="selected", Exposure2012="0.1", **bad)
        assert not reply["ok"] and "修改编号" in reply["error"], bad
    assert lr.writes() == 0


def test_nothing_to_change_and_too_many_changes(lr):
    assert not lr.run("set_develop", photo="selected", edit="e1")["ok"]
    from lightroom_mcp import edits

    many = {k: "0" for k in [k for k in edits.LIMITS if k not in edits.WB_KEYS][:31]}
    for k in many:
        lr.set_value(k, 0)
    reply = lr.run("set_develop", photo="selected", edit="e1", **many)
    assert not reply["ok"] and "最多改 30" in reply["error"] and lr.writes() == 0


def test_unknown_photo_id_is_refused(lr):
    reply = lr.run("set_develop", photo="NOT-A-REAL-ID", edit="e1", Exposure2012="0.1")
    assert not reply["ok"] and "找不到这张照片" in reply["error"] and lr.writes() == 0


def test_verified_is_false_when_lightroom_stores_a_different_value(lr):
    lr.set_flag("round_to", 0.5)  # Lightroom rounds to 0.5: 0.3 -> 0.5
    reply = lr.run("set_develop", photo="selected", edit="e1", Exposure2012="0.3")
    assert reply["ok"] and reply["data"]["verified"] is False and reply["data"]["after"]["Exposure2012"] == 0.5


def test_the_history_step_is_named_after_the_edit(lr):
    lr.run("set_develop", photo="selected", edit="20261102-120000-ab12", Exposure2012="0.1")
    # (the fake keeps the name passed to applyDevelopSettings)
    assert lr.writes() == 1


def test_white_balance_is_written_as_custom_and_restore_writes_the_old_label_back(lr):
    reply = lr.run("set_develop", photo="selected", edit="w1", Temperature="6400", Tint="20")
    assert reply["ok"] and reply["data"]["verified"] is True and reply["data"]["before_wb"] == "As Shot"
    assert lr.values()["WhiteBalance"] == "Custom" and lr.values()["Temperature"] == 6400
    back = lr.run("set_develop", photo="selected", edit="w2", restore="1", wb="As_Shot", Temperature="5600", Tint="13")
    assert back["ok"] and lr.values()["WhiteBalance"] == "As Shot" and lr.values()["Temperature"] == 5600


def test_white_balance_step_limit_and_range(lr):
    reply = lr.run("set_develop", photo="selected", edit="w1", Temperature="7000")
    assert not reply["ok"] and "单次最多改" in reply["error"]
    reply = lr.run("set_develop", photo="selected", edit="w1", Tint="200")
    assert not reply["ok"] and "取值范围" in reply["error"]
    assert lr.writes() == 0


def test_white_balance_on_a_photo_without_kelvin_values_is_refused_clearly(lr):
    lr.set_flag("fail_read", "Temperature")  # what a JPEG looks like
    reply = lr.run("set_develop", photo="selected", edit="w1", Temperature="5700")
    assert not reply["ok"] and "JPEG" in reply["error"] and lr.writes() == 0


def test_unknown_white_balance_label_is_ignored_on_restore(lr):
    back = lr.run("set_develop", photo="selected", edit="w2", restore="1", wb="Evil_Label", Temperature="5600")
    assert back["ok"] and lr.values()["WhiteBalance"] == "Custom"
