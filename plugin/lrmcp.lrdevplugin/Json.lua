-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
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
	-- JSON only escapes ASCII control bytes; %c depends on the process locale
	-- and can match bytes inside a UTF-8 character on Windows.
	local escaped = s:gsub('[%z\1-\31"\\]', function(c)
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

-- Strict decoder for the values the server sends back when restoring (preset undo). Size and depth are limited;
-- "null" members are skipped. Raises error({ lrmcp = message }) on bad input.
local MAX_DEPTH = 8
local STRING_ESCAPES = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }

local function utf8char(code)
	if code < 0x80 then
		return string.char(code)
	elseif code < 0x800 then
		return string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40)
	end
	return string.char(0xE0 + math.floor(code / 0x1000), 0x80 + math.floor(code / 0x40) % 0x40, 0x80 + code % 0x40)
end

function Json.decode(text)
	local pos = 1
	local function bad(message)
		error({ lrmcp = "收到的数据格式不对（" .. message .. "），已取消。" }, 0)
	end
	local function skip()
		pos = text:find("%S", pos) or (#text + 1)
	end
	local parseValue

	local function parseString()
		local out = {}
		pos = pos + 1
		while true do
			local c = text:sub(pos, pos)
			if c == "" then
				bad("字符串没有结束")
			elseif c == '"' then
				pos = pos + 1
				return table.concat(out)
			elseif c == "\\" then
				local n = text:sub(pos + 1, pos + 1)
				if STRING_ESCAPES[n] then
					out[#out + 1] = STRING_ESCAPES[n]
					pos = pos + 2
				elseif n == "u" then
					local hex = text:sub(pos + 2, pos + 5)
					if not hex:match("^%x%x%x%x$") then
						bad("u 转义不对")
					end
					out[#out + 1] = utf8char(tonumber(hex, 16))
					pos = pos + 6
				else
					bad("未知的转义")
				end
			else
				out[#out + 1] = c
				pos = pos + 1
			end
		end
	end

	parseValue = function(depth)
		if depth > MAX_DEPTH then
			bad("嵌套太深")
		end
		skip()
		local c = text:sub(pos, pos)
		if c == "{" then
			local obj = {}
			pos = pos + 1
			skip()
			if text:sub(pos, pos) == "}" then
				pos = pos + 1
				return obj
			end
			while true do
				skip()
				if text:sub(pos, pos) ~= '"' then
					bad("对象的键必须是字符串")
				end
				local key = parseString()
				skip()
				if text:sub(pos, pos) ~= ":" then
					bad("缺少冒号")
				end
				pos = pos + 1
				obj[key] = parseValue(depth + 1)
				skip()
				local d = text:sub(pos, pos)
				pos = pos + 1
				if d == "}" then
					return obj
				elseif d ~= "," then
					bad("对象里缺少逗号")
				end
			end
		elseif c == "[" then
			local arr = {}
			pos = pos + 1
			skip()
			if text:sub(pos, pos) == "]" then
				pos = pos + 1
				return arr
			end
			while true do
				local v = parseValue(depth + 1)
				if v == nil then
					bad("数组里不能有 null")
				end
				arr[#arr + 1] = v
				skip()
				local d = text:sub(pos, pos)
				pos = pos + 1
				if d == "]" then
					return arr
				elseif d ~= "," then
					bad("数组里缺少逗号")
				end
			end
		elseif c == '"' then
			return parseString()
		elseif text:sub(pos, pos + 3) == "true" then
			pos = pos + 4
			return true
		elseif text:sub(pos, pos + 4) == "false" then
			pos = pos + 5
			return false
		elseif text:sub(pos, pos + 3) == "null" then
			pos = pos + 4
			return nil
		end
		local num = text:match("^-?%d+%.?%d*[eE]?[+-]?%d*", pos)
		local value = num and tonumber(num)
		if value == nil or value ~= value or value == math.huge or value == -math.huge then
			bad("无法识别的内容")
		end
		pos = pos + #num
		return value
	end

	local result = parseValue(1)
	skip()
	if pos <= #text then
		bad("末尾有多余的内容")
	end
	return result
end

function Json.encode(v)
	local out = {}
	encode(v, out)
	return table.concat(out)
end

return Json
