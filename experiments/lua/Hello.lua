-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Menu item: Library > Plug-in Extras > "LrMCP: Hello (experiment 1)".
-- Read-only: reports version, sandbox facts and the open catalog, then shows
-- the same text in a dialog and writes it to the log.
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrLogger = import "LrLogger"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp1")
logger:enable("logfile")

LrTasks.startAsyncTask(function()
	local lines = {}
	local function add(text)
		lines[#lines + 1] = text
		logger:info(text)
	end

	local ok, err = LrTasks.pcall(function()
		local v = LrApplication.versionTable()
		add(string.format("LrC %d.%d.%d (build %s)", v.major, v.minor, v.revision, tostring(v.build_version)))
		add("WIN_ENV=" .. tostring(WIN_ENV))

		add("sandbox: os.getenv=" .. type(os.getenv)
			.. " os.execute=" .. type(os.execute)
			.. " io.open=" .. type(io.open)
			.. " io.popen=" .. type(io.popen))

		local catalog = LrApplication.activeCatalog()
		add("catalog=" .. tostring(catalog:getPath()))
		add("photos in catalog=" .. tostring(#catalog:getAllPhotos()))
	end)

	if not ok then
		add("ERROR: " .. tostring(err))
	end

	LrDialogs.message("LrMCP experiment 1", table.concat(lines, "\n"), "info")
end)
