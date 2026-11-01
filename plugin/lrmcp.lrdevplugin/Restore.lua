-- Menu item: "LrMCP: Restore white balance (experiment 4b)".
-- Select the same TEST photo used in experiment 4. It
--   1. writes WhiteBalance = "As Shot" back,
--   2. compares every simple develop setting with the dump taken at the start of experiment 4's last run
--      (~/LrMcp/exp4_<format>_<name>_settings.txt) and logs the differences,
--   3. retries deleting the leftover "LrMCP-exp4" snapshots (by snapshotID and by id_global).
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp4b")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")

LrTasks.startAsyncTask(function()
	local catalog = LrApplication.activeCatalog()
	local photo = catalog:getTargetPhoto()
	if not photo then
		LrDialogs.message("LrMCP experiment 4b", "Select the test photo first.", "info")
		return
	end
	local path = photo:getRawMetadata("path")
	if not path:find("ceshi", 1, true) then
		LrDialogs.message("LrMCP experiment 4b", "Refusing: not in the 'ceshi' test folder.", "info")
		return
	end
	local tag = tostring(photo:getRawMetadata("fileFormat")) .. "_" .. LrPathUtils.removeExtension(LrPathUtils.leafName(path))
	log("=== experiment 4b on " .. path .. " ===")

	local function wb()
		local s = photo:getDevelopSettings()
		return string.format("WhiteBalance=%s Temperature=%s Tint=%s", tostring(s.WhiteBalance), tostring(s.Temperature),
			tostring(s.Tint))
	end
	log("before: " .. wb())

	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP restore WB", function()
			photo:applyDevelopSettings({ WhiteBalance = "As Shot" }, "LrMCP restore WB")
		end)
	end)
	log("apply WhiteBalance='As Shot': ok=" .. tostring(ok) .. " err=" .. tostring(err))
	log("after:  " .. wb())

	-- Compare with the baseline dump
	local baseline = LrPathUtils.child(dir, "exp4_" .. tag .. "_settings.txt")
	local diffs = {}
	if LrFileUtils.exists(baseline) then
		local current = photo:getDevelopSettings()
		local compared = 0
		for line in (LrFileUtils.readFile(baseline) .. "\n"):gmatch("([^\n]*)\n") do
			local key, value = line:match("^(%S+) = (.*)$")
			if key and not value:find("^<table") then
				compared = compared + 1
				if tostring(current[key]) ~= value then
					diffs[#diffs + 1] = string.format("%s: baseline=%s now=%s", key, value, tostring(current[key]))
				end
			end
		end
		log(string.format("compared %d simple settings with baseline; %d differ", compared, #diffs))
		for _, d in ipairs(diffs) do
			log("DIFF " .. d)
		end
	else
		log("baseline file not found: " .. baseline)
	end

	-- Retry deleting leftover snapshots
	local deleted = 0
	for _, snap in ipairs(photo:getDevelopSnapshots() or {}) do
		if snap.name == "LrMCP-exp4" then
			for _, which in ipairs({ "snapshotID", "id_global" }) do
				local stillThere = false
				for _, s2 in ipairs(photo:getDevelopSnapshots() or {}) do
					if s2.name == "LrMCP-exp4" then
						stillThere = true
					end
				end
				if stillThere then
					LrTasks.pcall(function()
						catalog:withWriteAccessDo("LrMCP delete snapshot", function()
							photo:deleteDevelopSnapshot(snap[which])
						end)
					end)
					local after = 0
					for _, s2 in ipairs(photo:getDevelopSnapshots() or {}) do
						if s2.name == "LrMCP-exp4" then
							after = after + 1
						end
					end
					log(string.format("deleteDevelopSnapshot via %s -> snapshots named LrMCP-exp4 now: %d", which, after))
					if after == 0 then
						deleted = deleted + 1
					end
				end
			end
		end
	end
	local remaining = 0
	for _, s in ipairs(photo:getDevelopSnapshots() or {}) do
		if s.name == "LrMCP-exp4" then
			remaining = remaining + 1
		end
	end
	log("leftover LrMCP-exp4 snapshots: " .. remaining)

	LrDialogs.message("LrMCP experiment 4b",
		"Done. See LrMcpExp4b.log. Diffs: " .. #diffs .. ", leftover snapshots: " .. remaining, "info")
end)
