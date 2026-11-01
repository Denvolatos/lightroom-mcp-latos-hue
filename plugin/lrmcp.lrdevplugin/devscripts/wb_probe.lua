-- Dev script: measure white balance writes on ONE RAW and ONE JPEG of the TEST catalog, then restore everything.
-- Reports: slider range behaviour, JPEG semantics, how long Temperature/Tint take to appear, and whether the
-- restore brings back ALL simple settings.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"
local LrDate = import "LrDate"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local function find(name)
	for _, p in ipairs(catalog:getAllPhotos()) do
		if LrPathUtils.leafName(p:getRawMetadata("path")) == name then return p end
	end
end
local function simple(s)
	local out = {}
	for k, v in pairs(s) do if type(v) ~= "table" then out[k] = tostring(v) end end
	return out
end
local function write(photo, settings)
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP wb probe", function() photo:applyDevelopSettings(settings, "LrMCP wb probe") end)
	end)
	return ok and "" or (" ERROR " .. tostring(err))
end
local function wb(photo)
	local s = photo:getDevelopSettings()
	return string.format("WB=%s Temp=%s Tint=%s", tostring(s.WhiteBalance), tostring(s.Temperature), tostring(s.Tint))
end
local lines = {}
local function say(t) lines[#lines + 1] = t end

local function run(name, tempTests, tintTests, custom)
	local photo = find(name)
	if not photo then say(name .. ": not found") return end
	local before = simple(photo:getDevelopSettings())
	local raw = photo:getDevelopSettings()
	say("== " .. name .. " start: " .. wb(photo))
	for _, t in ipairs(tempTests) do
		local e = write(photo, { WhiteBalance = "Custom", Temperature = t })
		say(string.format("Temperature %s -> %s%s", tostring(t), wb(photo), e))
	end
	for _, t in ipairs(tintTests) do
		local e = write(photo, { WhiteBalance = "Custom", Tint = t })
		say(string.format("Tint %s -> %s%s", tostring(t), wb(photo), e))
	end
	-- restore: explicit values if there were any, otherwise "As Shot" only
	local restore = { WhiteBalance = raw.WhiteBalance }
	if raw.Temperature ~= nil then restore.Temperature = raw.Temperature end
	if raw.Tint ~= nil then restore.Tint = raw.Tint end
	local e = write(photo, restore)
	-- JPEG: wait and see whether Temperature/Tint show up later
	local t0 = LrDate.currentTime()
	local seen
	for _ = 1, 20 do
		local s = photo:getDevelopSettings()
		if before.Temperature == nil and s.Temperature ~= nil then seen = LrDate.currentTime() - t0 break end
		LrTasks.sleep(0.5)
	end
	say("after restore: " .. wb(photo) .. e .. (seen and string.format(" (Temperature appeared after %.1fs)", seen) or ""))
	local after = simple(photo:getDevelopSettings())
	local diffs = {}
	for k, v in pairs(before) do if after[k] ~= v then diffs[#diffs + 1] = k .. ":" .. v .. "->" .. tostring(after[k]) end end
	for k, v in pairs(after) do if before[k] == nil then diffs[#diffs + 1] = k .. ":nil->" .. v end end
	say("differences vs start: " .. (#diffs == 0 and "none" or table.concat(diffs, ", ")))
end

run("DSC08151.ARW", { 2000, 2500, 7000, 50000, 60000, 1000 }, { -150, 150, 200, -200 })
run("DSC08205.JPG", { -100, -50, 0, 50, 100, 5500, 20000 }, { -150, 150, 200 })
return table.concat(lines, "\n")
