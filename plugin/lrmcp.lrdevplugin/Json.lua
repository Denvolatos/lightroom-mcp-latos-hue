-- Minimal JSON encoder (the SDK has none). Responses only; commands from the server are plain "key=value" text.
local Json = {}

local ARRAY = {}

-- Mark a table as a JSON array (needed for empty arrays, which would otherwise become {}).
function Json.array(t)
	return setmetatable(t or {}, ARRAY)
end

local escapes = {
	['"'] = '\\"',
	["\\"] = "\\\\",
	["\b"] = "\\b",
	["\f"] = "\\f",
	["\n"] = "\\n",
	["\r"] = "\\r",
	["\t"] = "\\t",
}

local function quote(s)
	local escaped = s:gsub('[%c"\\]', function(c)
		return escapes[c] or string.format("\\u%04x", c:byte())
	end)
	return '"' .. escaped .. '"'
end

local function isArray(t)
	if getmetatable(t) == ARRAY then
		return true
	end
	local n = #t
	if n == 0 then
		return false
	end
	local count = 0
	for _ in pairs(t) do
		count = count + 1
	end
	return count == n
end

local encode

local function encodeTable(t, out)
	if isArray(t) then
		out[#out + 1] = "["
		for i = 1, #t do
			if i > 1 then
				out[#out + 1] = ","
			end
			encode(t[i], out)
		end
		out[#out + 1] = "]"
		return
	end
	local keys = {}
	for k in pairs(t) do
		keys[#keys + 1] = tostring(k)
	end
	table.sort(keys)
	out[#out + 1] = "{"
	for i, k in ipairs(keys) do
		if i > 1 then
			out[#out + 1] = ","
		end
		out[#out + 1] = quote(k)
		out[#out + 1] = ":"
		local v = t[k]
		if v == nil then
			v = t[tonumber(k)]
		end
		encode(v, out)
	end
	out[#out + 1] = "}"
end

encode = function(v, out)
	local kind = type(v)
	if v == nil then
		out[#out + 1] = "null"
	elseif kind == "boolean" then
		out[#out + 1] = v and "true" or "false"
	elseif kind == "number" then
		if v ~= v or v == math.huge or v == -math.huge then
			out[#out + 1] = "null"
		elseif v == math.floor(v) and math.abs(v) < 1e15 then
			out[#out + 1] = string.format("%d", v)
		else
			out[#out + 1] = string.format("%.10g", v)
		end
	elseif kind == "string" then
		out[#out + 1] = quote(v)
	elseif kind == "table" then
		encodeTable(v, out)
	else
		out[#out + 1] = quote(tostring(v))
	end
end

function Json.encode(v)
	local out = {}
	encode(v, out)
	return table.concat(out)
end

return Json
