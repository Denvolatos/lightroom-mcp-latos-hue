-- The plug-in's side of the local bridge: polls the Python server (GET /poll) for whitelisted commands,
-- runs them, and answers with POST /result. Started from Init.lua. State is shared through _G.LrMcp
-- (Status.lua reads it, Stop.lua sets .stop).
local LrDate = import "LrDate"
local LrFileUtils = import "LrFileUtils"
local LrHttp = import "LrHttp"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local Commands = require "Commands.lua"
local Json = require "Json.lua"
local Version = require "Version.lua"

-- Development helper: present only in dev builds (the release package does not contain DevRun.lua).
local hasDev, DevRun = pcall(require, "DevRun.lua")

local logger = LrLogger("LrMcp")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

local BASE = "http://127.0.0.1:58770"
local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")
local gen = tostring(LrDate.currentTime())

_G.LrMcp = { version = Version, connected = false, lastOk = nil, lastError = nil, stop = false }
local state = _G.LrMcp

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

-- "cmd <id> <command> key=value ..."  or (dev builds only)  "run <id> <script name>"
local function parse(body)
	local words = {}
	for w in body:gmatch("%S+") do
		words[#words + 1] = w
	end
	if words[1] == "cmd" and #words >= 3 then
		local params = {}
		for i = 4, #words do
			local k, v = words[i]:match("^([%w_]+)=(.*)$")
			if k then
				params[k] = v
			end
		end
		return "cmd", words[2], words[3], params
	elseif words[1] == "run" and #words >= 3 then
		return "run", words[2], words[3]
	end
end

local function execute(command, params)
	local t0 = LrDate.currentTime()
	local ok, res = LrTasks.pcall(Commands.run, command, params)
	local ms = (LrDate.currentTime() - t0) * 1000
	if ok then
		log(string.format("command %s ok (%.0f ms)", command, ms))
		return Json.encode({ ok = true, data = res })
	end
	local message = type(res) == "table" and res.lrmcp or ("插件内部错误：" .. tostring(res))
	log(string.format("command %s failed (%.0f ms): %s", command, ms, tostring(message)))
	return Json.encode({ ok = false, error = message })
end

local function post(token, id, text)
	LrHttp.post(BASE .. "/result?id=" .. id, text, authHeaders(token), "POST", 20)
end

LrTasks.startAsyncTask(function()
	log("bridge loop starting, plug-in " .. Version .. ", gen=" .. gen)
	local token, fails = nil, 0
	while not state.stop do
		token = token or readToken()
		if not token then
			state.connected = false
			LrTasks.sleep(2)
		else
			local headers = authHeaders(token, {
				{ field = "X-Gen", value = gen },
				{ field = "X-Plugin-Version", value = Version },
			})
			local body, hdrs = LrHttp.get(BASE .. "/poll", headers, 15)
			local status = hdrs and hdrs.status
			if status == 200 and body then
				fails = 0
				state.connected, state.lastOk, state.lastError = true, LrDate.currentTime(), nil
				if body == "stop" then
					log("told to stop by a newer plug-in instance")
					state.connected = false
					return
				end
				local kind, id, a, b = parse(body)
				if kind == "cmd" then
					post(token, id, execute(a, b))
				elseif kind == "run" then
					if hasDev and DevRun.enabled() then
						post(token, id, DevRun.run(id, a))
					else
						post(token, id, "REFUSED: dev mode is off")
					end
				end
			elseif status == 401 then
				token = nil
				LrTasks.sleep(2)
			else
				fails = fails + 1
				state.connected = false
				state.lastError = (hdrs and hdrs.error and hdrs.error.errorCode) or tostring(status)
				LrTasks.sleep(math.min(5, 1 + fails))
			end
		end
	end
	state.connected = false
	log("bridge loop ended")
end)
