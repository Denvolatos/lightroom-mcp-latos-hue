-- The plug-in's side of the local bridge. Every running lrmcp server (one per AI session) announces itself in
-- ~/LrMcp/servers/<port>.txt (port, token, pid). This file polls ALL of them (GET /poll), runs the whitelisted
-- command each one asks for and answers with POST /result. Commands from different servers run one at a time.
-- Started from Init.lua. State is shared through _G.LrMcp (Status.lua reads it, Stop.lua sets .stop).
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

local FIRST_PORT, PORT_COUNT = 58770, 20 -- the range the servers use; anything else is ignored
local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")
local serversDir = LrPathUtils.child(dir, "servers")
local legacyTokenPath = LrPathUtils.child(dir, "token") -- written by a 0.2.x server, which always uses FIRST_PORT

_G.LrMcp = { version = Version, connected = false, lastOk = nil, lastError = nil, stop = false, servers = {} }
local state = _G.LrMcp

-- One command at a time, even when several servers (AI sessions) ask at the same moment. Tasks are cooperative,
-- so nothing can slip in between the test of `busy` and setting it.
local busy = false
local function exclusive(fn, ...)
	while busy do
		LrTasks.sleep(0.05)
	end
	busy = true
	local ok, res = LrTasks.pcall(fn, ...)
	busy = false
	return ok, res
end

local function readKeyValues(path)
	if not LrFileUtils.exists(path) then
		return nil
	end
	local text = LrFileUtils.readFile(path)
	if not text then
		return nil
	end
	local values = {}
	for line in text:gmatch("[^\r\n]+") do
		local k, v = line:match("^(%w+)=(.*)$")
		if k then
			values[k] = v
		end
	end
	return values
end

local function readLegacyToken()
	if not LrFileUtils.exists(legacyTokenPath) then
		return nil
	end
	local text = LrFileUtils.readFile(legacyTokenPath)
	return text and (text:gsub("%s+", ""))
end

local function authHeaders(token, extra)
	local headers = { { field = "Authorization", value = "Bearer " .. token } }
	for _, h in ipairs(extra or {}) do
		headers[#headers + 1] = h
	end
	return headers
end

local function refreshOverall()
	local any, newest = false, nil
	for _, s in pairs(state.servers) do
		if s.connected then
			any = true
			if not newest or (s.lastOk or 0) > newest then
				newest = s.lastOk
			end
		end
	end
	state.connected, state.lastOk = any, newest or state.lastOk
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
	local ok, res = exclusive(Commands.run, command, params)
	local ms = (LrDate.currentTime() - t0) * 1000
	if ok then
		log(string.format("command %s ok (%.0f ms)", command, ms))
		return Json.encode({ ok = true, data = res })
	end
	local message = type(res) == "table" and res.lrmcp or ("插件内部错误：" .. tostring(res))
	log(string.format("command %s failed (%.0f ms): %s", command, ms, tostring(message)))
	return Json.encode({ ok = false, error = message })
end

local function post(base, token, id, text)
	LrHttp.post(base .. "/result?id=" .. id, text, authHeaders(token), "POST", 20)
end

-- Polls one server until its announcement disappears or the plug-in is told to stop.
-- infoPath == nil means the legacy server (0.2.x) that only left ~/LrMcp/token.
local function pollServer(port, infoPath)
	local base = "http://127.0.0.1:" .. port
	local gen = tostring(LrDate.currentTime()) -- a newer plug-in instance (after a reload) has a larger gen
	local entry = state.servers[port]
	local token, fails = nil, 0
	log(string.format("polling server on port %d, plug-in %s, gen=%s", port, Version, gen))
	while not state.stop do
		local announced = infoPath and LrFileUtils.exists(infoPath) or (not infoPath and LrFileUtils.exists(legacyTokenPath))
		if not announced then
			break -- the server is gone
		end
		if not token then
			if infoPath then
				local info = readKeyValues(infoPath)
				token = info and info.token
			else
				token = readLegacyToken()
			end
		end
		if not token then
			entry.connected = false
			LrTasks.sleep(2)
		else
			local headers = authHeaders(token, {
				{ field = "X-Gen", value = gen },
				{ field = "X-Plugin-Version", value = Version },
			})
			local body, hdrs = LrHttp.get(base .. "/poll", headers, 15)
			local status = hdrs and hdrs.status
			if status == 200 and body then
				fails = 0
				entry.connected, entry.lastOk, entry.lastError = true, LrDate.currentTime(), nil
				refreshOverall()
				if body == "stop" then
					log("told to stop by a newer plug-in instance")
					state.stop = true
					break
				end
				local kind, id, a, b = parse(body)
				if kind == "cmd" then
					post(base, token, id, execute(a, b))
				elseif kind == "run" then
					if hasDev and DevRun.enabled() then
						local _, result = exclusive(DevRun.run, id, a)
						post(base, token, id, tostring(result))
					else
						post(base, token, id, "REFUSED: dev mode is off")
					end
				end
			elseif status == 401 then
				token = nil -- the server restarted with a new token: read the announcement again
				LrTasks.sleep(2)
			else
				fails = fails + 1
				entry.connected = false
				entry.lastError = (hdrs and hdrs.error and hdrs.error.errorCode) or tostring(status)
				refreshOverall()
				LrTasks.sleep(math.min(5, 1 + fails))
			end
		end
	end
	entry.connected = false
	state.servers[port] = nil
	refreshOverall()
	log(string.format("stopped polling port %d", port))
end

-- Looks for announcements every 2 seconds and starts a poller for each new server.
LrTasks.startAsyncTask(function()
	log("bridge manager starting, plug-in " .. Version)
	local running = {}
	while not state.stop do
		local wanted = {}
		if LrFileUtils.exists(serversDir) then
			for path in LrFileUtils.files(serversDir) do
				local port = tonumber(LrPathUtils.leafName(path):match("^(%d+)%.txt$"))
				if port and port >= FIRST_PORT and port < FIRST_PORT + PORT_COUNT then
					wanted[port] = path
				end
			end
		end
		if wanted[FIRST_PORT] == nil and LrFileUtils.exists(legacyTokenPath) then
			wanted[FIRST_PORT] = false -- a 0.2.x server
		end
		for port, path in pairs(wanted) do
			if not running[port] then
				running[port] = true
				state.servers[port] = { connected = false }
				LrTasks.startAsyncTask(function()
					pollServer(port, path or nil)
					running[port] = nil
				end)
			end
		end
		LrTasks.sleep(2)
	end
	state.connected = false
	log("bridge manager ended")
end)
