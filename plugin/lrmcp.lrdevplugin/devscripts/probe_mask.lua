-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: can a plain linear-gradient mask be written through applyDevelopSettings (no UI)? TEST catalog only.
-- Writes one mask, reads it back, clears it, and compares the whole settings snapshot with the start.
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

local function ser(v)
	if type(v) ~= "table" then return type(v) == "string" and string.format("%q", v) or tostring(v) end
	local keys = {}
	for k in pairs(v) do keys[#keys + 1] = k end
	table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
	local parts = {}
	for _, k in ipairs(keys) do parts[#parts + 1] = tostring(k) .. "=" .. ser(v[k]) end
	return "{" .. table.concat(parts, ",") .. "}"
end
local function write(settings)
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP mask probe", function() photo:applyDevelopSettings(settings, "LrMCP mask probe") end)
	end)
	return ok and "ok" or ("ERROR " .. tostring(err))
end
local lines = {}
local function say(t) lines[#lines + 1] = t end

local start = photo:getDevelopSettings()
local startSer = ser(start)
say("start has masks: " .. tostring(type(start.MaskGroupBasedCorrections) == "table" and next(start.MaskGroupBasedCorrections) ~= nil))

local mask = {
	{
		CorrectionAmount = 1,
		CorrectionActive = true,
		CorrectionName = "LrMCP test gradient",
		CorrectionSyncID = "11111111-2222-3333-4444-555555555555",
		LocalExposure2012 = -1.0,
		CorrectionMasks = {
			{
				What = "Mask/Gradient",
				MaskActive = true,
				MaskName = "Linear Gradient 1",
				MaskBlendMode = 0,
				MaskInverted = false,
				MaskSyncID = "66666666-7777-8888-9999-000000000000",
				MaskValue = 1,
				ZeroX = 0.5, ZeroY = 0.0, FullX = 0.5, FullY = 0.4,
			},
		},
	},
}
say("write gradient mask: " .. write({ MaskGroupBasedCorrections = mask }))
local mid = photo:getDevelopSettings().MaskGroupBasedCorrections
say("read back: " .. (type(mid) == "table" and next(mid) ~= nil and ser(mid):sub(1, 1500) or "nothing"))
say("clear (empty table): " .. write({ MaskGroupBasedCorrections = {} }))
local after = photo:getDevelopSettings()
say("masks after clear: " .. tostring(type(after.MaskGroupBasedCorrections) == "table" and next(after.MaskGroupBasedCorrections) ~= nil))

local function diffKeys(a, b)
	local keys, out = {}, {}
	for k in pairs(a) do keys[k] = true end
	for k in pairs(b) do keys[k] = true end
	for k in pairs(keys) do if ser(a[k]) ~= ser(b[k]) then out[#out + 1] = k end end
	table.sort(out)
	return out
end
local d = diffKeys(start, after)
say("settings differing from start: " .. (#d == 0 and "none" or table.concat(d, ",")))
say("snapshot identical: " .. tostring(ser(after) == startSer))
return table.concat(lines, "\n")
