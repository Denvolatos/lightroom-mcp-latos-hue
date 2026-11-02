-- Dev script (READ ONLY): which develop presets exist and what kind of settings do they carry?
-- Output is ASCII only (counts and key names).
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"

local META = { CompatibleVersion = true, Version = true, ProcessVersion = true, FilterList = true, UUID = true, Name = true, SupportsAmount = true }
local total, plain, withMasks, withOther = 0, 0, 0, 0
local otherKeys, plainKeys = {}, {}
local function hasEntries(t) return type(t) == "table" and next(t) ~= nil end
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	for _, preset in ipairs(folder:getDevelopPresets()) do
		total = total + 1
		local s = preset:getSetting() or {}
		local masks = hasEntries(s.MaskGroupBasedCorrections)
		local other = false
		for k, v in pairs(s) do
			if not META[k] and k ~= "MaskGroupBasedCorrections" then
				plainKeys[k] = (plainKeys[k] or 0) + 1
				if type(v) == "table" then otherKeys[k] = (otherKeys[k] or 0) + 1; other = true end
			end
		end
		if masks then withMasks = withMasks + 1 elseif other then withOther = withOther + 1 else plain = plain + 1 end
	end
end
local function list(t) local o = {} for k, n in pairs(t) do o[#o + 1] = k .. "x" .. n end table.sort(o) return table.concat(o, ",") end
return string.format("total=%d | with masks=%d | with other table settings=%d | plain scalar presets=%d\nscalar+table keys seen: %s\ntable keys: %s",
	total, withMasks, withOther, plain, list(plainKeys), list(otherKeys))
