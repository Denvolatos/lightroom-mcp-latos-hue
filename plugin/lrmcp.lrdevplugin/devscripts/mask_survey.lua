-- Dev script (READ ONLY): what do mask settings inside presets look like? ASCII output, truncated.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"

local function hasEntries(t) return type(t) == "table" and next(t) ~= nil end
local function ser(v, depth)
	depth = depth or 0
	if type(v) ~= "table" then return type(v) == "string" and ("'" .. v:gsub("[^%w%p ]", "?") .. "'") or tostring(v) end
	if depth > 6 then return "{...}" end
	local keys = {}
	for k in pairs(v) do keys[#keys + 1] = k end
	table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
	local parts = {}
	for _, k in ipairs(keys) do parts[#parts + 1] = tostring(k) .. "=" .. ser(v[k], depth + 1) end
	return "{" .. table.concat(parts, ",") .. "}"
end
local whatCounts, shown, lines = {}, 0, {}
local function collectWhat(t)
	if type(t) ~= "table" then return end
	if t.What then whatCounts[t.What] = (whatCounts[t.What] or 0) + 1 end
	for _, v in pairs(t) do collectWhat(v) end
end
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	for _, preset in ipairs(folder:getDevelopPresets()) do
		local m = (preset:getSetting() or {}).MaskGroupBasedCorrections
		if hasEntries(m) then
			collectWhat(m)
			local text = ser(m)
			if shown < 40 and (text:find("Gradient", 1, true) or text:find("Brush", 1, true)) and not text:find("AI", 1, true) and #lines < 3 then
				shown = shown + 1
				lines[#lines + 1] = "PRESET: " .. text:sub(1, 1800)
			end
		end
	end
end
local w = {}
for k, n in pairs(whatCounts) do w[#w + 1] = k .. "x" .. n end
table.sort(w)
return "mask kinds (What): " .. table.concat(w, ", ") .. "\n" .. table.concat(lines, "\n\n")
