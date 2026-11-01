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
	},

	VERSION = { major = 0, minor = 0, revision = 2, build = "exp2" },
}
