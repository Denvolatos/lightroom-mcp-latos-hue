-- Menu item: "LrMCP: HTTP test (experiment 2)".
-- Talks to server/exp2_server.py on 127.0.0.1 (read-only for Lightroom: touches no photos).
-- Tests: auth ok / wrong token / Origin header / latency / slow reply / timeout.
local LrDate = import "LrDate"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrHttp = import "LrHttp"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp2")
logger:enable("logfile")

local BASE = "http://127.0.0.1:58770"

-- Returns token (or nil) and a diagnostic string saying which path was tried and why it failed.
local function readToken()
	local home = LrPathUtils.getStandardFilePath("home")
	local dir = LrPathUtils.child(home, "LrMcp")
	local path = LrPathUtils.child(dir, "token")

	-- Compare io.open with the SDK's own LrFileUtils, to learn which one works.
	local selfPath = LrPathUtils.child(_PLUGIN.path, "Info.lua")
	local selfF, selfErr = io.open(selfPath, "rb")
	if selfF then
		selfF:close()
	end
	local exists = LrFileUtils.exists(path)
	local ioF, ioErr = io.open(path, "rb")
	if ioF then
		ioF:close()
	end
	local diag = string.format("path=%s | LrFileUtils.exists=%s readable=%s | io.open(token)=%s | io.open(own Info.lua)=%s",
		path, tostring(exists), tostring(LrFileUtils.isReadable(path)),
		ioF and "ok" or tostring(ioErr), selfF and "ok" or tostring(selfErr))

	if not exists then
		return nil, diag
	end
	local text = LrFileUtils.readFile(path)
	if not text then
		return nil, diag .. " | readFile returned nil"
	end
	return (text:gsub("%s+", "")), diag
end

-- Returns body, status, errorCode, elapsed milliseconds.
local function get(path, token, extraHeaders, timeout)
	local headers = {}
	if token then
		headers[#headers + 1] = { field = "Authorization", value = "Bearer " .. token }
	end
	for _, h in ipairs(extraHeaders or {}) do
		headers[#headers + 1] = h
	end
	local t0 = LrDate.currentTime()
	local body, hdrs = LrHttp.get(BASE .. path, headers, timeout)
	local ms = (LrDate.currentTime() - t0) * 1000
	local status = hdrs and hdrs.status
	local err = hdrs and hdrs.error and hdrs.error.errorCode
	return body, status, err, ms
end

LrTasks.startAsyncTask(function()
	local lines = {}
	local function add(text)
		lines[#lines + 1] = text
		logger:info(text)
	end
	local function show(name, body, status, err, ms)
		add(string.format("%s: status=%s err=%s %.0fms body=%s",
			name, tostring(status), tostring(err), ms, tostring(body)))
	end

	local ok, e = LrTasks.pcall(function()
		local token, diag = readToken()
		add("token lookup: " .. tostring(diag))
		if not token then
			add("no token file")
			return
		end
		add("token length=" .. #token)

		show("T1 ping", get("/ping", token, nil, 5))
		show("T2 wrong token", get("/ping", "wrong", nil, 5))
		show("T3 with Origin", get("/ping", token, { { field = "Origin", value = "http://evil.example" } }, 5))

		local total, worst = 0, 0
		local N = 10
		for _ = 1, N do
			local _, _, _, ms = get("/ping", token, nil, 5)
			total = total + ms
			if ms > worst then
				worst = ms
			end
		end
		add(string.format("T4 latency over %d pings: avg=%.1fms worst=%.1fms", N, total / N, worst))

		show("T5 slow 3s, timeout 10", get("/slow?s=3", token, nil, 10))
		show("T6 slow 5s, timeout 2", get("/slow?s=5", token, nil, 2))
	end)
	if not ok then
		add("ERROR: " .. tostring(e))
	end

	LrDialogs.message("LrMCP experiment 2", table.concat(lines, "\n"), "info")
end)
