-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: batch 1 (colour grading, calibration, parametric tone curve, point curves) on the TEST catalog.
-- For each key: current value, then nominal min / max / one step beyond each end as seen by getDevelopSettings(),
-- then the original is written back. At the end ALL simple settings are compared with the start.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local photo
for _, p in ipairs(catalog:getAllPhotos()) do
	if LrPathUtils.leafName(p:getRawMetadata("path")) == "DSC08238.ARW" then photo = p end
end
if not photo then return "DSC08238.ARW not found" end

local function simple(s)
	local out = {}
	for k, v in pairs(s) do if type(v) ~= "table" then out[k] = tostring(v) end end
	return out
end
local function write(settings)
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP probe", function() photo:applyDevelopSettings(settings, "LrMCP probe") end)
	end)
	return ok and "" or (" ERROR " .. tostring(err))
end
local function dump(v)
	if type(v) ~= "table" then return tostring(v) end
	local parts = {}
	for i = 1, math.min(#v, 24) do parts[#parts + 1] = dump(v[i]) end
	return "{" .. table.concat(parts, ",") .. "}"
end

local startAll = photo:getDevelopSettings()
local start = simple(startAll)
local lines = {}
local function say(t) lines[#lines + 1] = t end

local plan = {
	{ "SplitToningShadowHue", 0, 360 }, { "SplitToningShadowSaturation", 0, 100 }, { "ColorGradeShadowLum", -100, 100 },
	{ "SplitToningHighlightHue", 0, 360 }, { "SplitToningHighlightSaturation", 0, 100 }, { "ColorGradeHighlightLum", -100, 100 },
	{ "ColorGradeMidtoneHue", 0, 360 }, { "ColorGradeMidtoneSat", 0, 100 }, { "ColorGradeMidtoneLum", -100, 100 },
	{ "ColorGradeGlobalHue", 0, 360 }, { "ColorGradeGlobalSat", 0, 100 }, { "ColorGradeGlobalLum", -100, 100 },
	{ "SplitToningBalance", -100, 100 }, { "ColorGradeBlending", 0, 100 },
	{ "ShadowTint", -100, 100 }, { "RedHue", -100, 100 }, { "RedSaturation", -100, 100 }, { "GreenHue", -100, 100 },
	{ "GreenSaturation", -100, 100 }, { "BlueHue", -100, 100 }, { "BlueSaturation", -100, 100 },
	{ "ParametricShadows", -100, 100 }, { "ParametricDarks", -100, 100 }, { "ParametricLights", -100, 100 },
	{ "ParametricHighlights", -100, 100 }, { "ParametricShadowSplit", 0, 100 }, { "ParametricMidtoneSplit", 0, 100 },
	{ "ParametricHighlightSplit", 0, 100 },
}
for _, item in ipairs(plan) do
	local key, lo, hi = item[1], item[2], item[3]
	local original = startAll[key]
	local row = { key .. " start=" .. tostring(original) }
	for _, v in ipairs({ lo, hi, lo - 1, hi + 1 }) do
		local e = write({ [key] = v })
		row[#row + 1] = string.format("%s->%s%s", tostring(v), tostring(photo:getDevelopSettings()[key]), e)
	end
	if original ~= nil then write({ [key] = original }) else write({ [key] = 0 }) end
	say(table.concat(row, " | "))
end

-- point curves: what does the table look like, and can we write one?
for _, key in ipairs({ "ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue" }) do
	say(key .. " start=" .. dump(startAll[key]))
end
local e = write({ ToneCurvePV2012 = { 0, 0, 64, 56, 192, 200, 255, 255 } })
say("write ToneCurvePV2012 {0,0,64,56,192,200,255,255}" .. e .. " -> " .. dump(photo:getDevelopSettings().ToneCurvePV2012))
local e2 = write({ ToneCurvePV2012 = startAll.ToneCurvePV2012 })
say("restore curve" .. e2 .. " -> " .. dump(photo:getDevelopSettings().ToneCurvePV2012))

local after = simple(photo:getDevelopSettings())
local diffs = {}
for k, v in pairs(start) do if after[k] ~= v then diffs[#diffs + 1] = k .. ":" .. v .. "->" .. tostring(after[k]) end end
for k, v in pairs(after) do if start[k] == nil then diffs[#diffs + 1] = k .. ":nil->" .. v end end
table.sort(diffs)
say("differences vs start: " .. (#diffs == 0 and "none" or table.concat(diffs, ", ")))
return table.concat(lines, "\n")
