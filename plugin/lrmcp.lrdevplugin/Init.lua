-- Runs when the plug-in is loaded. Only writes one log line, to learn whether
-- LrForceInitPlugin makes Init run at startup / when added in Plug-in Manager.
local LrLogger = import "LrLogger"
local LrDate = import "LrDate"

local logger = LrLogger("LrMcpExp1")
logger:enable("logfile")
logger:info("Init.lua ran at LrDate.currentTime()=" .. tostring(LrDate.currentTime()))
