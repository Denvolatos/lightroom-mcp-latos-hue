-- Dev script: compile every plug-in file (syntax check) and test the Lua JSON encoder. Changes nothing.
local ctx = ...
local import = ctx.import
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"

local lines = {}
local function add(text)
	lines[#lines + 1] = text
end

local files = { "Info.lua", "Init.lua", "Version.lua", "Json.lua", "Commands.lua", "Bridge.lua", "DevRun.lua", "Status.lua", "Stop.lua" }
local chunks = {}
for _, name in ipairs(files) do
	local path = LrPathUtils.child(ctx.plugin.path, name)
	local code = LrFileUtils.exists(path) and LrFileUtils.readFile(path)
	if not code then
		add("MISSING " .. name)
	else
		local chunk, err = loadstring(code, "@" .. name)
		chunks[name] = chunk
		add((chunk and "OK      " or "SYNTAX  ") .. name .. (err and (": " .. err) or ""))
	end
end

-- JSON encoder tests (Json.lua has no imports, so it can run standalone)
if chunks["Json.lua"] then
	local Json = chunks["Json.lua"]()
	local function check(label, got, want)
		add(string.format("%s %s: %s", got == want and "PASS" or "FAIL", label, got == want and got or (got .. "  (want " .. want .. ")")))
	end
	check("object keys sorted", Json.encode({ b = 1, a = "x" }), '{"a":"x","b":1}')
	check("array", Json.encode({ 1, 2, 3 }), "[1,2,3]")
	check("empty marked array", Json.encode(Json.array({})), "[]")
	check("empty table is object", Json.encode({}), "{}")
	check("nested", Json.encode({ ok = true, data = { list = Json.array({}), n = 2.5 } }), '{"data":{"list":[],"n":2.5},"ok":true}')
	check("escapes", Json.encode({ s = 'a"b\\c\nd' }), '{"s":"a\\"b\\\\c\\nd"}')
	check("integer-valued float", Json.encode({ n = 3.0 }), '{"n":3}')
	check("nan becomes null", Json.encode({ n = 0 / 0 }), '{"n":null}')
	check("utf8 passes through", Json.encode({ s = "中文" }), '{"s":"中文"}')
	check("nil value omitted", Json.encode({ a = 1, b = nil }), '{"a":1}')
end
return table.concat(lines, "\n")
