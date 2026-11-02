-- Dev script: batch 2 (sharpening, noise reduction, vignette, grain) on the TEST catalog.
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
	{ "Sharpness", 0, 150 }, { "SharpenRadius", 0.5, 3 }, { "SharpenDetail", 0, 100 }, { "SharpenEdgeMasking", 0, 100 },
	{ "LuminanceSmoothing", 0, 100 }, { "LuminanceNoiseReductionDetail", 0, 100 }, { "LuminanceNoiseReductionContrast", 0, 100 },
	{ "ColorNoiseReduction", 0, 100 }, { "ColorNoiseReductionDetail", 0, 100 }, { "ColorNoiseReductionSmoothness", 0, 100 },
	{ "PostCropVignetteAmount", -100, 100 }, { "PostCropVignetteMidpoint", 0, 100 }, { "PostCropVignetteFeather", 0, 100 },
	{ "PostCropVignetteRoundness", -100, 100 }, { "PostCropVignetteHighlightContrast", 0, 100 },
	{ "GrainAmount", 0, 100 }, { "GrainSize", 0, 100 }, { "GrainFrequency", 0, 100 },
	{ "VignetteAmount", -100, 100 }, { "VignetteMidpoint", 0, 100 },
	{ "DefringePurpleAmount", 0, 20 }, { "DefringeGreenAmount", 0, 20 },
	{ "PostCropVignetteStyle", 1, 3 },
}
for _, item in ipairs(plan) do
	local key, lo, hi = item[1], item[2], item[3]
	local original = startAll[key]
	local row = { key .. " start=" .. tostring(original) }
	local d = (key == "SharpenRadius") and 0.1 or 1
	for _, v in ipairs({ lo, hi, lo - d, hi + d }) do
		local e = write({ [key] = v })
		row[#row + 1] = string.format("%s->%s%s", tostring(v), tostring(photo:getDevelopSettings()[key]), e)
	end
	if original ~= nil then write({ [key] = original }) end
	say(table.concat(row, " | "))
end

local after = simple(photo:getDevelopSettings())
local diffs = {}
for k, v in pairs(start) do if after[k] ~= v then diffs[#diffs + 1] = k .. ":" .. v .. "->" .. tostring(after[k]) end end
for k, v in pairs(after) do if start[k] == nil then diffs[#diffs + 1] = k .. ":nil->" .. v end end
table.sort(diffs)
say("differences vs start: " .. (#diffs == 0 and "none" or table.concat(diffs, ", ")))
return table.concat(lines, "\n")
