-- Dev script (READ ONLY): which preset folders does Lightroom have, where do they live, and how many presets are in each?
-- Tells Adobe's built-in presets (inside the program) from user presets (inside the user's own settings folder).
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"

local lines = {}
local total = 0
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	local presets = folder:getDevelopPresets()
	total = total + #presets
	local ok, path = pcall(function() return folder:getPath() end)
	lines[#lines + 1] = string.format("%s | %d presets | path: %s", tostring(folder:getName()), #presets, ok and tostring(path) or "(no path)")
end
lines[#lines + 1] = "total presets: " .. total
return table.concat(lines, string.char(10))
