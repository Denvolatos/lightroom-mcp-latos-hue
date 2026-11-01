-- DEVELOPMENT ONLY (excluded from release builds). Used by Bridge.lua.
-- Runs a Lua test script by NAME from this plug-in's own devscripts/ folder, and only while the flag file
-- ~/LrMcp/dev_enabled exists (created by the dev server, removed when it stops).
local LrFileUtils = import "LrFileUtils"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpDev")
logger:enable("logfile")

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")
local flag = LrPathUtils.child(dir, "dev_enabled")
local scriptsDir = LrPathUtils.child(_PLUGIN.path, "devscripts")

local M = {}

function M.enabled()
	return LrFileUtils.exists(flag) ~= false
end

-- Plain file name only: letters, digits, _ and -, ending in .lua. No path separators, no "..".
local function validName(name)
	return name:match("^[%w_%-]+%.lua$") ~= nil
end

function M.run(jobId, name)
	local result
	if not validName(name) then
		result = "REFUSED: not a plain script name"
	else
		local path = LrPathUtils.child(scriptsDir, name)
		local code = LrFileUtils.exists(path) and LrFileUtils.readFile(path)
		if not code then
			result = "REFUSED: no such script in devscripts/"
		else
			local chunk, err = loadstring(code, "@" .. name)
			if not chunk then
				result = "LOAD ERROR: " .. tostring(err)
			else
				local ctx = {
					import = import,
					plugin = _PLUGIN,
					dir = dir,
					jobId = jobId,
					log = function(text)
						logger:info("[script] " .. tostring(text))
					end,
				}
				local ok, res = LrTasks.pcall(chunk, ctx)
				result = ok and tostring(res) or ("ERROR: " .. tostring(res))
			end
		end
	end
	logger:info(string.format("job %s %s -> %d chars", tostring(jobId), name, #result))
	return result
end

return M
