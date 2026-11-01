-- Menu item: "LrMCP: WB keys probe (experiment 4d)".
-- For every selected photo in the 'ceshi' test folder (max 8): read WhiteBalance/Temperature/Tint,
-- do a NO-OP write (Exposure2012 = its current value), read again. Changes no values; tells us whether a
-- first write makes the (As Shot) Temperature/Tint keys appear, for RAW and for JPEG.
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp4d")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

LrTasks.startAsyncTask(function()
	local catalog = LrApplication.activeCatalog()
	local photos = catalog:getTargetPhotos()
	if not photos or #photos == 0 then
		LrDialogs.message("LrMCP experiment 4d", "Select the test photos first.", "info")
		return
	end
	log("=== experiment 4d: " .. #photos .. " selected ===")

	local function wb(photo)
		local s = photo:getDevelopSettings()
		return string.format("WhiteBalance=%s Temperature=%s Tint=%s", tostring(s.WhiteBalance), tostring(s.Temperature),
			tostring(s.Tint)), s
	end

	local done = 0
	for _, photo in ipairs(photos) do
		local path = photo:getRawMetadata("path")
		if done < 8 and path:find("ceshi", 1, true) then
			done = done + 1
			local name = LrPathUtils.leafName(path)
			local fmt = tostring(photo:getRawMetadata("fileFormat"))
			local before, s = wb(photo)
			log(string.format("%s (%s) BEFORE: %s | Exposure2012=%s keys=%d", name, fmt, before, tostring(s.Exposure2012), (function()
				local n = 0
				for _ in pairs(s) do
					n = n + 1
				end
				return n
			end)()))
			if type(s.Exposure2012) == "number" then
				local ok, err = LrTasks.pcall(function()
					catalog:withWriteAccessDo("LrMCP 4d no-op", function()
						photo:applyDevelopSettings({ Exposure2012 = s.Exposure2012 }, "LrMCP 4d no-op")
					end)
				end)
				log(name .. " no-op write ok=" .. tostring(ok) .. " err=" .. tostring(err))
				local after, s2 = wb(photo)
				log(string.format("%s AFTER:  %s | Exposure2012=%s", name, after, tostring(s2.Exposure2012)))
			end
		end
	end
	LrDialogs.message("LrMCP experiment 4d", "Done (" .. done .. " photos). See LrMcpExp4d.log.", "info")
end)
