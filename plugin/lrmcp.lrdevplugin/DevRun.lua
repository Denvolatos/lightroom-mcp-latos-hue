-- DEVELOPMENT ONLY (excluded from release builds). Started from Init.lua.
-- Polls the local dev bridge (server/dev_bridge.py) and runs a Lua test script by NAME from this plug-in's own
-- devscripts/ folder. Active only while the flag file ~/LrMcp/dev_enabled exists (the dev bridge creates it).
local LrDate = import "LrDate"
local LrFileUtils = import "LrFileUtils"
local LrHttp = import "LrHttp"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpDev")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")
local flag = LrPathUtils.child(dir, "dev_enabled")
local scriptsDir = LrPathUtils.child(_PLUGIN.path, "devscripts")
local BASE = "http://127.0.0.1:58770"
local gen = tostring(LrDate.currentTime())

local function readToken()
	local path = LrPathUtils.child(dir, "token")
	if not LrFileUtils.exists(path) then
		return nil
	end
	local text = LrFileUtils.readFile(path)
	return text and (text:gsub("%s+", ""))
end

local function authHeaders(token, extra)
	local headers = { { field = "Authorization", value = "Bearer " .. token } }
	for _, h in ipairs(extra or {}) do
		headers[#headers + 1] = h
	end
	return headers
end

-- Plain file name only: letters, digits, _ and -, ending in .lua. No path separators, no "..".
local function validName(name)
	return name:match("^[%w_%-]+%.lua$") ~= nil
end

local function runScript(jobId, name, token)
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
	log(string.format("job %s %s -> %d chars", tostring(jobId), name, #result))
	LrHttp.post(BASE .. "/result?id=" .. jobId, result, authHeaders(token), "POST", 20)
end

LrTasks.startAsyncTask(function()
	log("dev loop starting, gen=" .. gen)
	local token, fails = nil, 0
	while LrFileUtils.exists(flag) do
		token = token or readToken()
		if not token then
			LrTasks.sleep(2)
		else
			local body, hdrs = LrHttp.get(BASE .. "/poll", authHeaders(token, { { field = "X-Gen", value = gen } }), 15)
			local status = hdrs and hdrs.status
			if status == 200 and body then
				fails = 0
				if body == "stop" then
					log("told to stop by a newer plug-in instance")
					return
				end
				local id, name = body:match("^run (%S+) (.+)$")
				if id then
					runScript(id, name, token)
				end
			elseif status == 401 then
				token = nil
				LrTasks.sleep(2)
			else
				fails = fails + 1
				LrTasks.sleep(math.min(5, 1 + fails))
			end
		end
	end
	log("dev loop ended (flag file missing)")
end)
