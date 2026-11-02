-- Dev script: apply real presets to a TEST photo and see whether writing back the old values of the keys they touch
-- restores the photo EXACTLY (all settings, tables included). Also: is the Lua io library usable inside the plug-in?
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

local lines = {}
local function say(t) lines[#lines + 1] = t end

local okIo, ioErr = pcall(function()
	local path = LrPathUtils.child(LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp"), "io_probe.txt")
	local f = assert(io.open(path, "w"))
	f:write("x")
	f:close()
	os.remove(path)
end)
say("io.open/write/remove usable: " .. tostring(okIo) .. (okIo and "" or (" (" .. tostring(ioErr) .. ")")))

local function deepcopy(v)
	if type(v) ~= "table" then return v end
	local c = {}
	for k, x in pairs(v) do c[k] = deepcopy(x) end
	return c
end
local function ser(v)
	if type(v) ~= "table" then return type(v) == "string" and string.format("%q", v) or tostring(v) end
	local keys = {}
	for k in pairs(v) do keys[#keys + 1] = k end
	table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
	local parts = {}
	for _, k in ipairs(keys) do parts[#parts + 1] = tostring(k) .. "=" .. ser(v[k]) end
	return "{" .. table.concat(parts, ",") .. "}"
end
local META = { CompatibleVersion = true, Version = true, ProcessVersion = true, FilterList = true, UUID = true, Name = true, SupportsAmount = true }
local function hasEntries(t) return type(t) == "table" and next(t) ~= nil end

-- find candidates
local want = { look = nil, bw = nil, curve = nil }
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	for _, preset in ipairs(folder:getDevelopPresets()) do
		local s = preset:getSetting() or {}
		if not hasEntries(s.MaskGroupBasedCorrections) then
			if s.Look ~= nil and not want.look then want.look = preset end
			if s.ConvertToGrayscale == true and not want.bw then want.bw = preset end
			if s.ToneCurvePV2012 ~= nil and s.Look == nil and s.ConvertToGrayscale ~= true and not want.curve then want.curve = preset end
		end
	end
end

local function trial(label, preset)
	if not preset then say(label .. ": no such preset found") return end
	local s = preset:getSetting()
	local touched = {}
	for k in pairs(s) do if not META[k] and k ~= "MaskGroupBasedCorrections" then touched[#touched + 1] = k end end
	local startAll = photo:getDevelopSettings()
	local startSer = ser(startAll)
	local old = {}
	for _, k in ipairs(touched) do old[k] = deepcopy(startAll[k]) end
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP preset probe", function() photo:applyDevelopPreset(preset) end)
	end)
	local mid = photo:getDevelopSettings()
	local changed = {}
	for _, k in ipairs(touched) do if ser(mid[k]) ~= ser(startAll[k]) then changed[#changed + 1] = k end end
	local midSer = ser(mid)
	local extra = {}
	local allKeys = {}
	for k in pairs(startAll) do allKeys[k] = true end
	for k in pairs(mid) do allKeys[k] = true end
	for k in pairs(allKeys) do
		if ser(startAll[k]) ~= ser(mid[k]) and old[k] == nil then
			extra[#extra + 1] = k .. (startAll[k] == nil and "(was nil)" or "")
			if startAll[k] ~= nil then old[k] = deepcopy(startAll[k]) end
		end
	end
	table.sort(extra)
	say(label .. " side-effect keys not listed by the preset: " .. (#extra == 0 and "none" or table.concat(extra, ",")))
	local ok2, err2 = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP preset probe restore", function() photo:applyDevelopSettings(old, "restore") end)
	end)
	local endAll = photo:getDevelopSettings()
	local diffs = {}
	local keys = {}
	for k in pairs(startAll) do keys[k] = true end
	for k in pairs(endAll) do keys[k] = true end
	for k in pairs(keys) do if ser(startAll[k]) ~= ser(endAll[k]) then diffs[#diffs + 1] = k end end
	table.sort(diffs)
	say(string.format("%s: touched %d keys, apply ok=%s%s, changed %d keys, restore ok=%s%s, applied state differs from start: %s, after restore differing keys: %s",
		label, #touched, tostring(ok), ok and "" or (" " .. tostring(err)), #changed, tostring(ok2), ok2 and "" or (" " .. tostring(err2)),
		tostring(midSer ~= startSer), #diffs == 0 and "none" or table.concat(diffs, ",")))
end
trial("look preset", want.look)
trial("black&white preset", want.bw)
trial("curve/colour preset", want.curve)
return table.concat(lines, "\n")
