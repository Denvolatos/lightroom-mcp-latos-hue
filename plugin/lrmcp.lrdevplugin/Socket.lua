-- Menu item: "LrMCP: Socket test (experiment 3)".
-- Opens two LrSocket servers (one "receive", one "send", ports chosen by the OS),
-- writes the ports to ~/LrMcp/sock_ports, then answers a Python client:
--   "auth <token>" -> "auth ok" / "auth fail";  "ping <n>" -> "pong <n>";
--   "big <data>" -> "len <bytes>";  "done" -> closes. Anything before auth -> "denied".
-- Touches no photos.
local LrDate = import "LrDate"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrFunctionContext = import "LrFunctionContext"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrSocket = import "LrSocket"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp3")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")

local function readToken()
	local path = LrPathUtils.child(dir, "token")
	if not LrFileUtils.exists(path) then
		return nil
	end
	local text = LrFileUtils.readFile(path)
	return text and (text:gsub("%s+", ""))
end

local function writePorts(recvPort, sendPort)
	local f = io.open(LrPathUtils.child(dir, "sock_ports"), "wb")
	if not f then
		log("cannot write sock_ports")
		return
	end
	f:write(string.format("recv=%d\nsend=%d\n", recvPort, sendPort))
	f:close()
	log("sock_ports written")
end

if _G.exp3Running then
	LrDialogs.message("LrMCP experiment 3", "Already running.", "info")
	return
end
_G.exp3Running = true

LrTasks.startAsyncTask(function()
	LrFunctionContext.callWithContext("lrmcp_exp3", function(context)
		local token = readToken()
		log("token present=" .. tostring(token ~= nil))

		local running = true
		local authed = false
		local recvPort, sendPort, portsWritten
		local sender

		local function maybeWritePorts()
			if recvPort and sendPort and not portsWritten then
				portsWritten = true
				writePorts(recvPort, sendPort)
			end
		end

		local function reply(text)
			sender:send(text .. "\n")
		end

		local function handle(message)
			log(string.format("recv len=%d first60=%q", #message, message:sub(1, 60)))
			local msg = (message:gsub("[\r\n]+$", ""))
			if msg:sub(1, 5) == "auth " then
				if token and msg:sub(6) == token then
					authed = true
					reply("auth ok")
				else
					reply("auth fail")
				end
			elseif not authed then
				reply("denied")
			elseif msg:sub(1, 5) == "ping " then
				reply("pong " .. msg:sub(6))
			elseif msg:sub(1, 4) == "big " then
				reply("len " .. #msg)
			elseif msg == "done" then
				running = false
			end
		end

		sender = LrSocket.bind({
			functionContext = context,
			plugin = _PLUGIN,
			address = "localhost",
			port = 0,
			mode = "send",
			onConnecting = function(_, port)
				sendPort = port
				log("send socket listening, port=" .. tostring(port))
				maybeWritePorts()
			end,
			onConnected = function()
				log("send socket: client connected")
			end,
			onMessage = function(_, message)
				log("send socket got unexpected message: " .. tostring(message))
			end,
			onClosed = function()
				log("send socket closed")
				running = false
			end,
			onError = function(socket, err)
				log("send socket error: " .. tostring(err))
				if err == "timeout" then
					socket:reconnect()
				end
			end,
		})

		local receiver = LrSocket.bind({
			functionContext = context,
			plugin = _PLUGIN,
			address = "localhost",
			port = 0,
			mode = "receive",
			onConnecting = function(_, port)
				recvPort = port
				log("receive socket listening, port=" .. tostring(port))
				maybeWritePorts()
			end,
			onConnected = function()
				log("receive socket: client connected")
			end,
			onMessage = function(_, message)
				handle(message)
			end,
			onClosed = function()
				log("receive socket closed")
				running = false
			end,
			onError = function(socket, err)
				log("receive socket error: " .. tostring(err))
				if err == "timeout" then
					socket:reconnect()
				end
			end,
		})

		local t0 = LrDate.currentTime()
		while running and (LrDate.currentTime() - t0) < 150 do
			LrTasks.sleep(0.2)
		end
		log(string.format("loop ended after %.1fs (running=%s)", LrDate.currentTime() - t0, tostring(running)))

		sender:close()
		receiver:close()
	end)

	_G.exp3Running = false
	LrDialogs.message("LrMCP experiment 3", "Finished. See log LrMcpExp3.log.", "info")
end)
