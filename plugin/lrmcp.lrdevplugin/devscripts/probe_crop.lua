-- Dev script: how does cropping behave through applyDevelopSettings? TEST catalog, DSC08238.ARW, then restore.
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
local KEYS = { "HasCrop", "CropLeft", "CropTop", "CropRight", "CropBottom", "CropAngle", "CropConstrainAspectRatio", "CropConstrainToWarp", "CropAspect" }
local function state()
	local s = photo:getDevelopSettings()
	local parts = {}
	for _, k in ipairs(KEYS) do parts[#parts + 1] = k .. "=" .. tostring(s[k]) end
	local d = photo:getRawMetadata("croppedDimensions")
	local o = photo:getRawMetadata("dimensions")
	parts[#parts + 1] = string.format("isCropped=%s cropped=%sx%s original=%sx%s", tostring(photo:getRawMetadata("isCropped")),
		tostring(d and d.width), tostring(d and d.height), tostring(o and o.width), tostring(o and o.height))
	return table.concat(parts, " ")
end

local startAll = photo:getDevelopSettings()
local start = simple(startAll)
local lines = {}
local function say(t) lines[#lines + 1] = t end
say("start: " .. state())

local tests = {
	{ "crop 10% each side", { CropLeft = 0.1, CropTop = 0.1, CropRight = 0.9, CropBottom = 0.9 } },
	{ "with HasCrop=true", { HasCrop = true, CropLeft = 0.2, CropTop = 0.2, CropRight = 0.8, CropBottom = 0.8 } },
	{ "angle 5", { CropAngle = 5 } },
	{ "angle 45", { CropAngle = 45 } },
	{ "angle -45", { CropAngle = -45 } },
	{ "angle 60 (beyond UI)", { CropAngle = 60 } },
	{ "angle 0", { CropAngle = 0 } },
	{ "left -0.1 (outside)", { CropLeft = -0.1 } },
	{ "right 1.1 (outside)", { CropRight = 1.1 } },
	{ "left 0.95 > right 0.8 (inverted)", { CropLeft = 0.95 } },
	{ "tiny crop 0.4..0.41", { CropLeft = 0.4, CropRight = 0.41, CropTop = 0.4, CropBottom = 0.41 } },
	{ "aspect 3:2 constrain", { CropConstrainAspectRatio = true, CropLeft = 0, CropTop = 0.1, CropRight = 1, CropBottom = 0.9 } },
}
for _, t in ipairs(tests) do
	local e = write(t[2])
	say(t[1] .. e .. " -> " .. state())
end

-- restore
local restore = {}
for _, k in ipairs({ "CropLeft", "CropTop", "CropRight", "CropBottom", "CropAngle" }) do restore[k] = startAll[k] end
local e = write(restore)
if startAll.HasCrop ~= nil then write({ HasCrop = startAll.HasCrop }) end
if startAll.CropConstrainAspectRatio ~= nil then write({ CropConstrainAspectRatio = startAll.CropConstrainAspectRatio }) end
say("restore" .. e .. " -> " .. state())

local after = simple(photo:getDevelopSettings())
local diffs = {}
for k, v in pairs(start) do if after[k] ~= v then diffs[#diffs + 1] = k .. ":" .. v .. "->" .. tostring(after[k]) end end
for k, v in pairs(after) do if start[k] == nil then diffs[#diffs + 1] = k .. ":nil->" .. v end end
table.sort(diffs)
say("differences vs start: " .. (#diffs == 0 and "none" or table.concat(diffs, ", ")))
return table.concat(lines, "\n")
