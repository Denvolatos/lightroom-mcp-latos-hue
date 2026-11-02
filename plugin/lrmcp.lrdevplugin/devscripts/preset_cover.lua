-- Dev script (READ ONLY): how many presets only carry settings that lr_set_develop could write and restore?
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local Limits = require "Limits.lua"

local META = { CompatibleVersion = true, Version = true, ProcessVersion = true, FilterList = true, UUID = true, Name = true, SupportsAmount = true }
local CURVES = { ToneCurvePV2012 = true, ToneCurvePV2012Red = true, ToneCurvePV2012Green = true, ToneCurvePV2012Blue = true }
local function hasEntries(t) return type(t) == "table" and next(t) ~= nil end
local total, ok, blockedBy, okNames = 0, 0, {}, {}
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	for _, preset in ipairs(folder:getDevelopPresets()) do
		total = total + 1
		local s = preset:getSetting() or {}
		local blockers = {}
		for k, v in pairs(s) do
			if META[k] then
			elseif k == "MaskGroupBasedCorrections" then
				if hasEntries(v) then blockers[#blockers + 1] = k end
			elseif not (Limits[k] or CURVES[k]) then
				blockers[#blockers + 1] = k
			end
		end
		if #blockers == 0 then
			ok = ok + 1
			if #okNames < 8 then okNames[#okNames + 1] = tostring(preset:getUuid()):sub(1, 8) end
		else
			for _, b in ipairs(blockers) do blockedBy[b] = (blockedBy[b] or 0) + 1 end
		end
	end
end
local o = {}
for k, n in pairs(blockedBy) do o[#o + 1] = { k, n } end
table.sort(o, function(a, b) return a[2] > b[2] end)
local top = {}
for i = 1, math.min(#o, 15) do top[#top + 1] = o[i][1] .. "x" .. o[i][2] end
return string.format("total=%d fully covered=%d\ntop blockers: %s", total, ok, table.concat(top, ", "))
