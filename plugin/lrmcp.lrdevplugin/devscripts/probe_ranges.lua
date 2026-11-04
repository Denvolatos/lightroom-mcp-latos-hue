-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: measure the real range of the develop sliders and what Lightroom does with out-of-range values.
-- Works only on the TEST catalog's selected photo. For each key it tries the nominal minimum, maximum and a value
-- beyond each end, reads back what Lightroom stored, then restores the original value. Ends by comparing all simple
-- develop settings with the state at the start.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local photo = catalog:getTargetPhoto()
if not photo then
	return "no selected photo"
end

local function simple(s)
	local out = {}
	for k, v in pairs(s) do
		if type(v) ~= "table" then
			out[k] = tostring(v)
		end
	end
	return out
end

local function write(settings, name)
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo(name, function()
			photo:applyDevelopSettings(settings, name)
		end)
	end)
	return ok, err
end

local start = simple(photo:getDevelopSettings())
local startRaw = photo:getDevelopSettings()

-- key, nominal min, nominal max
local plan = {
	{ "Exposure2012", -5, 5 },
	{ "Contrast2012", -100, 100 },
	{ "Highlights2012", -100, 100 },
	{ "Shadows2012", -100, 100 },
	{ "Whites2012", -100, 100 },
	{ "Blacks2012", -100, 100 },
	{ "Texture", -100, 100 },
	{ "Clarity2012", -100, 100 },
	{ "Dehaze", -100, 100 },
	{ "Vibrance", -100, 100 },
	{ "Saturation", -100, 100 },
	{ "HueAdjustmentRed", -100, 100 },
	{ "SaturationAdjustmentRed", -100, 100 },
	{ "LuminanceAdjustmentRed", -100, 100 },
}

local lines = { string.format("photo: %s", tostring(photo:getRawMetadata("path"))) }
local function try(key, value)
	local ok, err = write({ [key] = value }, "LrMCP probe")
	local got = photo:getDevelopSettings()[key]
	return string.format("%s -> %s%s", tostring(value), tostring(got), ok and "" or (" (ERROR " .. tostring(err) .. ")"))
end

for _, item in ipairs(plan) do
	local key, lo, hi = item[1], item[2], item[3]
	local original = startRaw[key]
	local beyond = (key == "Exposure2012") and 1 or 1
	local row = {
		"min " .. try(key, lo),
		"below min " .. try(key, lo - beyond),
		"max " .. try(key, hi),
		"above max " .. try(key, hi + beyond),
		"fraction " .. try(key, 0.123456),
	}
	write({ [key] = original }, "LrMCP probe restore")
	lines[#lines + 1] = string.format("%-24s (orig %s) | %s", key, tostring(original), table.concat(row, " | "))
end

-- everything back to the start?
local now = simple(photo:getDevelopSettings())
local diffs = {}
for k, v in pairs(start) do
	if now[k] ~= v then
		diffs[#diffs + 1] = k .. ": " .. v .. " -> " .. tostring(now[k])
	end
end
for k, v in pairs(now) do
	if start[k] == nil then
		diffs[#diffs + 1] = k .. ": (new) " .. v
	end
end
table.sort(diffs)
lines[#lines + 1] = "AFTER RESTORE: " .. #diffs .. " simple settings differ from the start" .. (#diffs > 0 and (": " .. table.concat(diffs, "; ")) or "")
return table.concat(lines, "\n")
