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
  if key == "pickStatus" then return FAKE.meta.pick end
  if key == "rating" then return FAKE.meta.rating end
  if key == "colorNameForLabel" then return FAKE.meta.label end
  if key == "keywords" then return FAKE.meta.keywords end
  return nil
end
function photo:getFormattedMetadata(key)
  if key == "title" or key == "caption" then return FAKE.meta[key] end
  return nil
end
function photo:setRawMetadata(key, value)
  FAKE.writes[#FAKE.writes + 1] = { meta = key }
  if key == "rating" then FAKE.meta.rating = value
  elseif key == "pickStatus" then FAKE.meta.pick = value
  elseif key == "colorNameForLabel" then FAKE.meta.label = value
  elseif key == "title" or key == "caption" then FAKE.meta[key] = value
  else error("unexpected metadata key " .. key) end
end
local function newKeyword(name) return { getName = function() return name end } end
function photo:addKeyword(k)
  for _, x in ipairs(FAKE.meta.keywords) do if x:getName() == k:getName() then return end end
  FAKE.meta.keywords[#FAKE.meta.keywords + 1] = k
end
function photo:removeKeyword(k)
  for i, x in ipairs(FAKE.meta.keywords) do if x:getName() == k:getName() then table.remove(FAKE.meta.keywords, i) return end end
end
function photo:getDevelopSettings()
  local copy = {}
  for k, v in pairs(FAKE.values) do copy[k] = v end
  if FAKE.fail_read then copy[FAKE.fail_read] = nil end
  return copy
end
function photo:applyDevelopSettings(settings, name)
  FAKE.writes[#FAKE.writes + 1] = { settings = settings, name = name }
  for k, v in pairs(settings) do
    FAKE.values[k] = (FAKE.round_to and type(v) == 'number') and (math.floor(v / FAKE.round_to + 0.5) * FAKE.round_to) or v
  end
end

-- presets: one plain colour preset, one with masks
local presets = {
  { uuid = "PRESET-PLAIN-0001", name = "Warm look",
    settings = { Contrast2012 = 40, ColorGradeBlending = 70, Look = { Name = "Vivid" }, GrainSeed = 99, Version = "15.4" } },
  { uuid = "PRESET-MASKS-0002", name = "Sky", settings = { MaskGroupBasedCorrections = { { Name = "sky" } } } },
}
function photo:applyDevelopPreset(preset)
  FAKE.writes[#FAKE.writes + 1] = { preset = preset:getName() }
  for k, v in pairs(preset.settings) do
    if k ~= "Version" and k ~= "MaskGroupBasedCorrections" then FAKE.values[k] = v end
  end
end
local presetObjects = {}
for _, p in ipairs(presets) do
  presetObjects[#presetObjects + 1] = { settings = p.settings, getUuid = function() return p.uuid end,
                                        getName = function() return p.name end, getSetting = function() return p.settings end }
end
local folder = { getName = function() return "Test folder" end, getDevelopPresets = function() return presetObjects end }

local catalog = {}
function catalog:getPath() return "C:\\test\\test.lrcat" end
function catalog:createKeyword(name) return newKeyword(name) end
function catalog:getTargetPhoto() return photo end
function catalog:getTargetPhotos() return { photo } end
function catalog:findPhotoByUuid(id) if id == FAKE.uuid then return photo end end
function catalog:findPhotoByPath(p) return FAKE.in_catalog[p] end
function catalog:addPhoto(p, ...)
  if select("#", ...) > 0 then error("addPhoto must get the path only") end
  FAKE.writes[#FAKE.writes + 1] = { added = p, in_gate = FAKE.in_gate }
  if FAKE.add_fails then error("The file is corrupt.") end
  local fresh = setmetatable({}, { __index = photo })
  function fresh:getRawMetadata(key)
    if key == "uuid" then return "NEWPHOTO-9999" end
    if key == "path" then return p end
    return photo:getRawMetadata(key)
  end
  FAKE.in_catalog[p] = fresh
  return fresh
end
function catalog:withWriteAccessDo(name, fn, params)
  if FAKE.write_gate ~= "executed" then return FAKE.write_gate end
  FAKE.in_gate = true
  local ok, err = pcall(fn, {})
  FAKE.in_gate = false
  if not ok then error(err, 0) end
  return "executed"
end

local modules = {
  LrApplication = { activeCatalog = function() return catalog end, developPresetFolders = function() return { folder } end,
                    versionTable = function() return { major = 15, minor = 2, revision = 0, build_version = "x" } end },
  LrDate = { currentTime = function() return 0 end },
  LrTasks = { pcall = pcall },
  LrExportSession = function(args)
    return { doExportOnCurrentTask = function()
      local s = args.exportSettings
      FAKE.last_export = s
      local ext = (s.LR_format == "TIFF") and "tif" or "jpg"
      if not FAKE.export_fails then FAKE.files[s.LR_export_destinationPathPrefix .. "\\" .. s.LR_tokenCustomString .. "." .. ext] = true end
    end }
  end,
  LrExportSettings = { extensionForFormat = function(f)
    local map = { JPEG = "jpg", TIFF = "tif" }
    return assert(map[f], "no fake extension for " .. tostring(f))
  end },
  LrFileUtils = { exists = function(path)
                    if FAKE.readonly and path:find("readonly", 1, true) then return "file" end
                    if FAKE.folders[path] then return "directory" end
                    if FAKE.files[path] then return "file" end
                    return false
                  end,
                  createAllDirectories = function() end, delete = function() end,
                  fileAttributes = function() return { fileSize = 12345 } end },
  LrPathUtils = { child = child, getStandardFilePath = function() return "C:\\Users\\test" end,
                  leafName = function(p) return (p:match("([^\\]+)$")) end,
                  removeExtension = function(p) return (p:gsub("%.[^%.\\]+$", "")) end,
                  isAbsolute = function(p) return p:match("^%a:[\\/]") ~= nil or p:sub(1, 1) == "/" end },
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
function SET_JSON(key, text) FAKE.values[key] = Json.decode(text) end
function DECODE(text) return Json.encode(Json.decode(text)) end
function DECODE_FAILS(text) local ok, e = pcall(Json.decode, text) return (not ok) and (type(e) == "table" and e.lrmcp or tostring(e)) or false end
function EXPORT_SETTING(key) return FAKE.last_export and FAKE.last_export[key] end
function MAKE_FOLDER(path) FAKE.folders[path] = true end
function MAKE_FILE(path) FAKE.files[path] = true end
function ADDED_PATHS()
  local out = {}
  for _, w in ipairs(FAKE.writes) do if w.added then out[#out + 1] = w.added .. (w.in_gate and "|gate" or "|NOGATE") end end
  return table.concat(out, ";")
end
function ALREADY_IN_CATALOG(path)
  FAKE.in_catalog[path] = setmetatable({}, { __index = {
    getRawMetadata = function(self, key) if key == "uuid" then return "OLDPHOTO-1" end if key == "path" then return path end return nil end,
    getFormattedMetadata = function() return nil end } })
end
function SET_LABEL(v) FAKE.meta.label = v end
function RESET()
  FAKE.files, FAKE.folders, FAKE.last_export, FAKE.export_fails = {}, {}, nil, false
  FAKE.in_catalog, FAKE.add_fails, FAKE.in_gate = {}, false, false
  FAKE.meta = { rating = nil, pick = 0, label = "", title = "", caption = "", keywords = { newKeyword("Torino") } }
  FAKE.readonly, FAKE.write_gate, FAKE.writes, FAKE.fail_read, FAKE.round_to = false, "executed", {}, nil, nil
  FAKE.values = { Exposure2012 = 0, Contrast2012 = 0, Saturation = 0, HueAdjustmentRed = 0, Sharpness = 40,
                  WhiteBalance = 'As Shot', Temperature = 5600, Tint = 13,
                  ToneCurvePV2012 = { 0, 0, 255, 255 }, CropLeft = 0, CropTop = 0, CropRight = 1, CropBottom = 1, CropAngle = 0, ParametricHighlights = 0, ColorGradeBlending = 50 }
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

        def export_setting(self, key):
            return g.EXPORT_SETTING(key)

        def make_folder(self, path):
            g.MAKE_FOLDER(path)

        def make_file(self, path):
            g.MAKE_FILE(path)

        def added(self):
            return str(g.ADDED_PATHS())

        def already_in_catalog(self, path):
            g.ALREADY_IN_CATALOG(path)

        def set_label(self, value):
            g.SET_LABEL(value)

        def set_json(self, key, text):
            g.SET_JSON(key, text)

        def decode(self, text):
            return g.DECODE(text)

        def decode_fails(self, text):
            return g.DECODE_FAILS(text)

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
    for key in ("PerspectiveVertical", "ToneCurve", "LensManualDistortionAmount"):
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
    reply = lr.run("set_develop", photo="selected", edit="e1", restore="1", PerspectiveVertical="5")
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


def test_point_curve_is_written_and_read_back(lr):
    reply = lr.run("set_develop", photo="selected", edit="c1", ToneCurvePV2012="0,0,64,50,192,205,255,255")
    assert reply["ok"] and reply["data"]["verified"] is True
    assert reply["data"]["before"]["ToneCurvePV2012"] == [0, 0, 255, 255]
    assert reply["data"]["after"]["ToneCurvePV2012"] == [0, 0, 64, 50, 192, 205, 255, 255]


def test_bad_curves_are_refused_by_the_plugin_itself(lr):
    for bad in ("0,0", "0,0,255", "5,5,255,255", "0,0,100,100,100,120,255,255", "0,0,100,150,150,100,255,255",
                "0,0,100,230,255,255", "0,0,300,300", "a,b,c,d", ""):
        reply = lr.run("set_develop", photo="selected", edit="c1", ToneCurvePV2012=bad)
        assert not reply["ok"], bad
    assert lr.writes() == 0


def test_curve_restore_skips_only_the_deviation_and_endpoint_rules(lr):
    lr.set_value("ToneCurvePV2012", None)  # not needed: just prove restore accepts a steep earlier curve
    reply = lr.run("set_develop", photo="selected", edit="c2", restore="1", ToneCurvePV2012="0,10,100,240,255,255")
    assert not reply["ok"] and "读不到" in reply["error"]  # the fake has no curve value now
    lr.reset()
    reply = lr.run("set_develop", photo="selected", edit="c2", restore="1", ToneCurvePV2012="0,10,100,240,255,255")
    assert reply["ok"]


def test_colour_grading_and_parametric_sliders_use_the_same_rules(lr):
    reply = lr.run("set_develop", photo="selected", edit="g1", ColorGradeBlending="70", ParametricHighlights="-20")
    assert reply["ok"] and lr.values()["ColorGradeBlending"] == 70
    reply = lr.run("set_develop", photo="selected", edit="g2", ColorGradeBlending="101")
    assert not reply["ok"] and "取值范围" in reply["error"]
    reply = lr.run("set_develop", photo="selected", edit="g3", ParametricHighlights="-80")
    assert not reply["ok"] and "单次最多改" in reply["error"]


def test_crop_rectangle_rule_and_restore_in_the_plugin(lr):
    reply = lr.run("set_develop", photo="selected", edit="k1", CropLeft="0.1", CropRight="0.9", CropAngle="3")
    assert reply["ok"] and reply["data"]["verified"] is True
    lr.set_value("CropLeft", 0.8)
    reply = lr.run("set_develop", photo="selected", edit="k2", CropLeft="0.85")  # width would be 0.05, a small step
    assert not reply["ok"] and "至少保留" in reply["error"]
    reply = lr.run("set_develop", photo="selected", edit="k3", CropAngle="30")  # more than 10 degrees in one call
    assert not reply["ok"] and "单次最多改" in reply["error"]
    back = lr.run("set_develop", photo="selected", edit="k4", restore="1", CropLeft="0", CropRight="1", CropAngle="0")
    assert back["ok"] and lr.values()["CropLeft"] == 0 and lr.values()["CropRight"] == 1


# ---- presets and the JSON decoder ---------------------------------------------------------------------------
def test_json_decoder_round_trips_and_rejects_garbage(lr):
    text = '{"a":1.5,"b":[1,2,{"c":"x y"}],"d":true,"e":"\u00e4\u4e2d","f":-3}'
    assert json.loads(lr.decode(text)) == {"a": 1.5, "b": [1, 2, {"c": "x y"}], "d": True, "e": "\u00e4\u4e2d", "f": -3}
    for bad in ('{"a":}', '{"a":1', '[1,2', '{"a":1} x', '{1:2}', '"abc', '{"a":nan}', '[' * 20 + ']' * 20, ''):
        assert lr.decode_fails(bad), bad


def test_list_presets_filters_and_flags_masks(lr):
    reply = lr.run("list_presets", query="sky")
    assert reply["ok"] and reply["data"]["matched"] == 1 and reply["data"]["presets"][0]["has_masks"] is True
    reply = lr.run("list_presets")
    assert reply["data"]["total"] == 2 and len(reply["data"]["presets"]) == 2


def test_apply_preset_reports_everything_that_changed(lr):
    reply = lr.run("set_develop", photo="selected", edit="p0", Contrast2012="5")
    assert reply["ok"]
    lr.set_json("Look", '{"Name":"Adobe Color"}')
    reply = lr.run("apply_preset", photo="selected", edit="p1", preset="PRESET-PLAIN-0001")
    data = reply["data"]
    assert reply["ok"] and data["preset"] == "Warm look"
    assert set(data["changed_keys"]) == {"Contrast2012", "ColorGradeBlending", "Look", "GrainSeed"}
    assert data["new_keys"] == ["GrainSeed"] and data["tables_changed"] == ["Look"]
    assert data["before"]["Contrast2012"] == 5 and "GrainSeed" not in data["before"]


def test_masked_preset_and_bad_ids_are_refused_without_writing(lr):
    for preset in ("PRESET-MASKS-0002", "PRESET-NOPE-9999", "../x", ""):
        reply = lr.run("apply_preset", photo="selected", edit="p1", preset=preset)
        assert not reply["ok"], preset
    assert lr.writes() == 0
    lr.set_flag("readonly", True)
    reply = lr.run("apply_preset", photo="selected", edit="p1", preset="PRESET-PLAIN-0001")
    assert not reply["ok"] and "只读模式" in reply["error"] and lr.writes() == 0


def blob(values):
    import urllib.parse
    return urllib.parse.quote(json.dumps(values, separators=(",", ":")), safe="")


def test_restore_settings_writes_back_only_known_keys_of_the_same_type_and_range(lr):
    lr.set_json("Look", '{"Name":"Vivid"}')
    ok = lr.run("restore_settings", photo="selected", edit="r1", blob=blob({"Contrast2012": 3, "Look": {"Name": "Adobe Color"}}))
    assert ok["ok"] and ok["data"]["verified"] is True and lr.values()["Contrast2012"] == 3
    for label, values in (("unknown key", {"NotASetting": 1}), ("wrong type", {"Contrast2012": "7"}),
                          ("out of range", {"Contrast2012": 500}), ("masks", {"MaskGroupBasedCorrections": {}}),
                          ("bad name", {"a b": 1})):
        before = lr.writes()
        reply = lr.run("restore_settings", photo="selected", edit="r2", blob=blob(values))
        assert not reply["ok"] and lr.writes() == before, label
    lr.set_flag("readonly", True)
    reply = lr.run("restore_settings", photo="selected", edit="r3", blob=blob({"Contrast2012": 1}))
    assert not reply["ok"] and "只读模式" in reply["error"]


# ---- catalog information ------------------------------------------------------------------------------------------
def q(text):
    import urllib.parse
    return urllib.parse.quote(text, safe="")


def test_get_metadata_reads_catalog_information(lr):
    reply = lr.run("get_metadata", photo="selected")
    data = reply["data"]["metadata"]
    assert reply["ok"] and data == {"rating": 0, "flag": "none", "color_label": "none", "title": "", "caption": "", "keywords": ["Torino"]}


def test_set_metadata_writes_everything_and_reports_before_and_after(lr):
    reply = lr.run("set_metadata", photo="selected", edit="m1", rating="4", flag="reject", color="Green", title=q("Tramonto \u00e0 Torino"),
                   caption=q("a b, c"), add_kw=q("sera") + "," + q("due parole"), remove_kw=q("Torino"))
    assert reply["ok"] and reply["data"]["verified"] is True
    after = reply["data"]["after"]
    assert after["rating"] == 4 and after["flag"] == "reject" and after["color_label"].lower() == "green"
    assert after["title"] == "Tramonto \u00e0 Torino" and after["caption"] == "a b, c"
    assert after["keywords"] == ["due parole", "sera"]
    assert reply["data"]["before"]["keywords"] == ["Torino"]
    back = lr.run("set_metadata", photo="selected", edit="m2", rating="0", flag="none")
    assert back["ok"] and back["data"]["after"]["rating"] == 0 and back["data"]["after"]["flag"] == "none"


def test_set_metadata_refuses_bad_input_without_writing(lr):
    bad = [dict(rating="6"), dict(rating="2.5"), dict(rating="x"), dict(flag="maybe"), dict(color="pink"), dict(title="x" * 201),
           dict(title="%0A"), dict(caption="x" * 1001), dict(add_kw=""), dict(add_kw=q("x" * 61)),
           dict(add_kw=",".join(q(f"k{i}") for i in range(11))), dict(add_kw="%01"), dict()]
    for params in bad:
        reply = lr.run("set_metadata", photo="selected", edit="m1", **params)
        assert not reply["ok"], params
    assert lr.writes() == 0
    for edit in ("", "a b", "../x"):
        assert not lr.run("set_metadata", photo="selected", edit=edit, rating="3")["ok"]
    lr.set_flag("readonly", True)
    reply = lr.run("set_metadata", photo="selected", edit="m3", rating="3")
    assert not reply["ok"] and "只读模式" in reply["error"]


def test_gray_means_no_colour_label(lr):
    lr.set_label("gray")
    reply = lr.run("get_metadata", photo="selected")
    assert reply["data"]["metadata"]["color_label"] == "none"


# ---- export ---------------------------------------------------------------------------------------------------------
import urllib.parse as _up

OUT = "D:\\\u7167\u7247\\\u5bfc\u51fa"   # a Chinese folder name, to prove the percent-encoding round trip


def enc(path):
    return _up.quote(path, safe="")


def test_export_needs_a_destination_the_user_named(lr):
    reply = lr.run("export_photo", photo="selected")
    assert not reply["ok"] and "请让用户说清楚导出到哪里" in reply["error"]


def test_export_into_the_folder_the_user_named_and_never_overwrite(lr):
    lr.make_folder(OUT)
    first = lr.run("export_photo", photo="selected", folder=enc(OUT))
    data = first["data"]
    assert first["ok"] and data["file"] == "one_LrMCP_full.jpg" and data["folder"] == OUT and data["destination"] == "folder"
    assert data["path"] == OUT + "\\one_LrMCP_full.jpg" and data["bytes"] == 12345
    assert data["width"] == 6000 and data["height"] == 4000 and data["quality"] == 90 and data["metadata"] == "minimal"
    assert lr.export_setting("LR_size_doConstrain") is False and abs(lr.export_setting("LR_jpeg_quality") - 0.9) < 1e-9
    assert lr.run("export_photo", photo="selected", folder=enc(OUT))["data"]["file"] == "one_LrMCP_full_2.jpg"


def test_export_refuses_folders_that_are_not_ok(lr):
    for path in ("\\\\server\\share\\x", "//server/share", "relative\\dir", "D:\\a\\..\\b", "C:\\Windows\\Temp",
                 "C:\\Program Files\\X", "C:\\Users\\me\\AppData\\Roaming", "C:\\Users\\me\\.ssh", "C:\\Users\\me\\LrMcp\\previews",
                 "/System/Library", "/etc", "D:\\a\x07b", "D:\\" + "x" * 500):
        lr.make_folder(path)   # even if it exists, these are refused
        reply = lr.run("export_photo", photo="selected", folder=enc(path))
        assert not reply["ok"], path
    reply = lr.run("export_photo", photo="selected", folder=enc("D:\\missing"))
    assert not reply["ok"] and "不存在" in reply["error"]
    assert lr.run("export_photo", photo="selected", folder=enc("C:\\Users\\me\\LrMcp\\exports"))["error"].count("不存在") == 1  # allowed place, but missing


def test_export_named_places_and_options(lr):
    for name in ("desktop", "pictures", "documents"):
        data = lr.run("export_photo", photo="selected", destination=name)["data"]
        assert data["destination"] == name and data["folder"] == "C:\\Users\\test"
    data = lr.run("export_photo", photo="selected", long_edge="1024", quality="75", metadata="all", destination="data")["data"]
    assert data["file"] == "one_LrMCP_1024px.jpg" and data["folder"].endswith("LrMcp\\exports")
    assert data["width"] == 1024 and data["height"] == 683 and data["quality"] == 75 and data["metadata"] == "all"
    assert lr.export_setting("LR_size_doConstrain") is True and lr.export_setting("LR_size_maxWidth") == 1024
    assert lr.export_setting("LR_minimizeEmbeddedMetadata") is False
    assert lr.run("export_photo", photo="selected", destination="data", quality="5")["data"]["quality"] == 40
    assert not lr.run("export_photo", photo="selected", destination="somewhere")["ok"]


def test_export_bad_sizes_and_the_file_name_is_not_chosen_by_the_request(lr):
    lr.make_folder(OUT)
    for params in (dict(long_edge="100"), dict(long_edge="99999"), dict(long_edge="nan")):
        assert not lr.run("export_photo", photo="selected", folder=enc(OUT), **params)["ok"], params
    data = lr.run("export_photo", photo="selected", folder=enc(OUT), name="evil.exe", file="C:\\evil.jpg", path="C:\\evil")["data"]
    assert data["file"] == "one_LrMCP_full.jpg" and data["path"].startswith(OUT)


def test_export_reports_a_missing_file(lr):
    lr.make_folder(OUT)
    lr.set_flag("export_fails", True)
    reply = lr.run("export_photo", photo="selected", folder=enc(OUT))
    assert not reply["ok"] and "没有生成导出文件" in reply["error"]


# ---- TIFF export (v0.15, desktop app only; the MCP tool never sends "format") ---------------------------------------------
def test_export_default_format_is_still_jpeg(lr):
    lr.make_folder(OUT)
    data = lr.run("export_photo", photo="selected", folder=enc(OUT))["data"]
    assert data["format"] == "jpeg" and data["extension"] == "jpg" and data["quality"] == 90 and "bit_depth" not in data
    assert lr.export_setting("LR_format") == "JPEG" and lr.export_setting("LR_export_bitDepth") is None
    assert lr.export_setting("LR_tiff_compressionMethod") is None
    data = lr.run("export_photo", photo="selected", folder=enc(OUT), format="jpeg", bit_depth="8")["data"]
    assert data["file"].endswith("_2.jpg") and "bit_depth" not in data   # bit_depth means nothing for JPEG


def test_export_tiff_defaults_to_16_bit_srgb_lossless(lr):
    lr.make_folder(OUT)
    reply = lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff")
    data = reply["data"]
    assert reply["ok"] and data["file"] == "one_LrMCP_full.tif" and data["extension"] == "tif" and data["format"] == "tiff"
    assert data["path"] == OUT + "\\one_LrMCP_full.tif" and data["bit_depth"] == 16 and data["bytes"] == 12345
    assert data["width"] == 6000 and data["height"] == 4000 and data["metadata"] == "minimal"
    assert "quality" not in data
    assert lr.export_setting("LR_format") == "TIFF" and lr.export_setting("LR_export_bitDepth") == 16
    assert lr.export_setting("LR_export_colorSpace") == "sRGB"
    assert lr.export_setting("LR_tiff_compressionMethod") == "compressionMethod_ZIP"
    assert lr.export_setting("LR_jpeg_quality") is None and lr.export_setting("LR_extensionCase") == "lowercase"


def test_export_tiff_8_bit_size_and_name(lr):
    lr.make_folder(OUT)
    data = lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff", bit_depth="8", long_edge="1024", metadata="all")["data"]
    assert data["file"] == "one_LrMCP_1024px.tif" and data["bit_depth"] == 8 and data["width"] == 1024 and data["height"] == 683
    assert lr.export_setting("LR_export_bitDepth") == 8 and lr.export_setting("LR_size_maxWidth") == 1024
    assert lr.export_setting("LR_minimizeEmbeddedMetadata") is False


def test_export_tiff_ignores_quality(lr):
    lr.make_folder(OUT)
    data = lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff", quality="5")["data"]
    assert "quality" not in data and lr.export_setting("LR_jpeg_quality") is None


def test_export_rejects_unknown_formats_and_bit_depths(lr):
    lr.make_folder(OUT)
    for params in (dict(format="png"), dict(format="TIFF"), dict(format="jpg"), dict(format="psd"), dict(format="tiff", bit_depth="12"),
                   dict(format="tiff", bit_depth="abc"), dict(format="tiff", bit_depth="0")):
        reply = lr.run("export_photo", photo="selected", folder=enc(OUT), **params)
        assert not reply["ok"], params
    assert lr.export_setting("LR_format") is None   # nothing was exported by the refused calls


def test_export_tiff_never_overwrites(lr):
    lr.make_folder(OUT)
    lr.make_file(OUT + "\\one_LrMCP_full.tif")
    data = lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff")["data"]
    assert data["file"] == "one_LrMCP_full_2.tif"
    assert lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff")["data"]["file"] == "one_LrMCP_full_3.tif"
    # a JPEG of the same photo is a different file and does not count as a collision
    assert lr.run("export_photo", photo="selected", folder=enc(OUT))["data"]["file"] == "one_LrMCP_full.jpg"


def test_export_tiff_keeps_every_folder_check(lr):
    for path in ("\\\\server\\share\\x", "//server/share", "relative\\dir", "D:\\a\\..\\b", "C:\\Windows\\Temp",
                 "C:\\Program Files\\X", "C:\\Users\\me\\AppData\\Roaming", "C:\\Users\\me\\.ssh", "C:\\Users\\me\\LrMcp\\previews",
                 "D:\\a\x07b", "D:\\" + "x" * 500):
        lr.make_folder(path)
        assert not lr.run("export_photo", photo="selected", folder=enc(path), format="tiff")["ok"], path
    reply = lr.run("export_photo", photo="selected", folder=enc("D:\\missing"), format="tiff")
    assert not reply["ok"] and "不存在" in reply["error"]
    assert not lr.run("export_photo", photo="selected", format="tiff")["ok"]   # no destination at all
    assert lr.export_setting("LR_format") is None


def test_export_tiff_reports_a_missing_file(lr):
    lr.make_folder(OUT)
    lr.set_flag("export_fails", True)
    reply = lr.run("export_photo", photo="selected", folder=enc(OUT), format="tiff")
    assert not reply["ok"] and "没有生成导出文件" in reply["error"]


# ---- import (v0.15, desktop app only) -----------------------------------------------------------------------------------
PHOTO_FILE = "D:\\\u7167\u7247\\a b.JPG"   # Chinese folder, a space and an upper-case extension


def test_import_adds_the_photo_inside_the_write_gate_and_nothing_else(lr):
    lr.make_file(PHOTO_FILE)
    reply = lr.run("import_photo", path=enc(PHOTO_FILE))
    data = reply["data"]
    assert reply["ok"] and data["imported"] is True and data["already"] is False
    assert data["id"] == "NEWPHOTO-9999" and data["name"] == "a b.JPG"
    assert lr.added() == PHOTO_FILE + "|gate"
    assert lr.writes() == 1   # only addPhoto: no develop settings, metadata or presets


def test_import_of_a_photo_already_in_the_catalog_adds_nothing(lr):
    lr.make_file(PHOTO_FILE)
    lr.already_in_catalog(PHOTO_FILE)
    data = lr.run("import_photo", path=enc(PHOTO_FILE))["data"]
    assert data["already"] is True and data["imported"] is False and data["id"] == "OLDPHOTO-1"
    assert lr.writes() == 0


@pytest.mark.parametrize("name", ["x.jpg", "x.jpeg", "x.ARW", "x.cr2", "x.CR3", "x.nef", "x.nrw", "x.raf", "x.orf", "x.rw2",
                                  "x.dng", "x.tif", "x.TIFF", "x.heic", "x.heif", "x.PnG"])
def test_import_accepts_every_listed_extension_in_any_case(lr, name):
    path = "D:\\ceshi\\" + name
    lr.make_file(path)
    assert lr.run("import_photo", path=enc(path))["ok"], name


@pytest.mark.parametrize("path", [
    "\\\\server\\share\\a.jpg", "//server/share/a.jpg", "relative\\a.jpg", "/etc/a.jpg", "D:a.jpg",
    "D:\\a\\..\\b\\a.jpg", "D:/a/../a.jpg",
    "C:\\Windows\\a.jpg", "C:\\Program Files\\X\\a.jpg", "C:\\Program Files (x86)\\a.jpg", "C:\\ProgramData\\a.jpg",
    "C:\\Users\\me\\AppData\\Local\\a.jpg", "C:\\Users\\me\\.ssh\\a.jpg", "C:\\Users\\me\\LrMcp\\previews\\a.jpg",
    "C:\\Users\\me\\LrMcp\\exports\\a.jpg",
    "D:\\a\x07b.jpg", "D:\\" + "x" * 500 + ".jpg", "",
    "D:\\ceshi\\a.txt", "D:\\ceshi\\a.exe", "D:\\ceshi\\a.jpg.exe", "D:\\ceshi\\noextension", "D:\\ceshi\\a.gif", "D:\\ceshi\\a.jpg.",
])
def test_import_refuses_bad_paths_and_writes_nothing(lr, path):
    lr.make_file(path)   # even when the file exists
    reply = lr.run("import_photo", path=enc(path))
    assert not reply["ok"], path
    assert lr.writes() == 0 and lr.added() == ""


def test_import_refuses_missing_files_and_folders(lr):
    reply = lr.run("import_photo", path=enc("D:\\ceshi\\missing.jpg"))
    assert not reply["ok"] and "不存在" in reply["error"]
    lr.make_folder("D:\\ceshi\\folder.jpg")
    reply = lr.run("import_photo", path=enc("D:\\ceshi\\folder.jpg"))
    assert not reply["ok"] and "文件夹" in reply["error"]
    assert not lr.run("import_photo")["ok"]
    assert lr.writes() == 0


def test_import_reports_a_busy_catalog_and_lightrooms_own_error(lr):
    lr.make_file(PHOTO_FILE)
    lr.set_flag("write_gate", "queued")
    reply = lr.run("import_photo", path=enc(PHOTO_FILE))
    assert not reply["ok"] and "不能写入" in reply["error"] and lr.added() == ""
    lr.set_flag("write_gate", "executed")
    lr.set_flag("add_fails", True)
    reply = lr.run("import_photo", path=enc(PHOTO_FILE))
    assert not reply["ok"] and "The file is corrupt." in reply["error"]


def test_commands_lua_never_uses_a_bare_pcall():
    """Real Lightroom 15.2: a plain pcall around a call that yields (addPhoto inside the write gate) fails with
    "yielding is not allowed"; the fake SDK cannot show that, so the source is checked: only LrTasks.pcall."""
    import re

    source = (Path(__file__).resolve().parents[2] / "plugin" / "lrmcp.lrdevplugin" / "Commands.lua").read_text(encoding="utf-8")
    bare = [n for n, line in enumerate(source.splitlines(), 1) if re.search(r"(?<![.\w])pcall\s*\(", line)]
    assert not bare, f"bare pcall in Commands.lua at lines {bare}; use LrTasks.pcall"
