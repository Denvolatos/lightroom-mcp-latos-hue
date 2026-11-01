-- Experiment 1: minimal plug-in. Reads only, changes nothing in the catalog.
return {
	LrSdkVersion = 15.0,
	LrSdkMinimumVersion = 6.0,

	LrToolkitIdentifier = "io.github.denvolatos.lrmcp",
	LrPluginName = "LrMCP (experiment 1)",

	LrInitPlugin = "Init.lua",
	LrForceInitPlugin = true,

	LrLibraryMenuItems = {
		{ title = "LrMCP: Hello (experiment 1)", file = "Hello.lua" },
		{ title = "LrMCP: HTTP test (experiment 2)", file = "Http.lua" },
		{ title = "LrMCP: Socket test (experiment 3)", file = "Socket.lua" },
		{ title = "LrMCP: Develop test (experiment 4)", file = "Develop.lua" },
		{ title = "LrMCP: Restore white balance (experiment 4b)", file = "Restore.lua" },
		{ title = "LrMCP: White balance test (experiment 4c)", file = "Wb.lua" },
		{ title = "LrMCP: WB keys probe (experiment 4d)", file = "Probe.lua" },
		{ title = "LrMCP: Prepare WB probe (experiment 4e)", file = "Prepare.lua" },
	},

	VERSION = { major = 0, minor = 0, revision = 8, build = "exp4e" },
}
