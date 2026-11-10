-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- LrMCP: lets Claude / Codex look at photos (read-only in v1.0). Not an Adobe product.
return {
	LrSdkVersion = 15.0,
	LrSdkMinimumVersion = 6.0,

	LrToolkitIdentifier = "io.github.denvolatos.lrmcp",
	LrPluginName = "LrMCP",

	LrInitPlugin = "Init.lua",
	LrForceInitPlugin = true,
	LrDisablePlugin = "Stop.lua",
	LrShutdownPlugin = "Stop.lua",

	LrLibraryMenuItems = {
		{ title = "LrMCP: Status", file = "Status.lua" },
	},

	-- Keep in sync with Version.lua
	VERSION = { major = 1, minor = 1, revision = 0, build = "dev" },
}
