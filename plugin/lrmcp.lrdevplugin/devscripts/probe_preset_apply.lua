-- Dev script (test catalog only): does photo:applyDevelopPreset change anything, with and without a second argument?
-- Applies the B&W preset PB01 to the selected photo, reports whether ConvertToGrayscale changed, then writes back the
-- settings it saved first.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local photo = catalog:getTargetPhoto()
if not photo then return "no photo selected" end
local preset
for _, folder in ipairs(LrApplication.developPresetFolders()) do
	for _, p in ipairs(folder:getDevelopPresets()) do
		if p:getName() == "PB01" then preset = p end
	end
end
if not preset then return "PB01 not found" end

local before = photo:getDevelopSettings()
local out = { "gray before: " .. tostring(before.ConvertToGrayscale) }

local function gray() return tostring(photo:getDevelopSettings().ConvertToGrayscale) end
local function undo()
	catalog:withWriteAccessDo("LrMCP probe restore", function() photo:applyDevelopSettings({ ConvertToGrayscale = before.ConvertToGrayscale or false }) end, { timeout = 15 })
end

local r1 = catalog:withWriteAccessDo("LrMCP probe A", function() photo:applyDevelopPreset(preset) end, { timeout = 15 })
out[#out + 1] = "A (one argument): " .. tostring(r1) .. " gray now: " .. gray()
LrTasks.sleep(1)
out[#out + 1] = "A after 1s: " .. gray()
undo()

local rB = catalog:withWriteAccessDo("LrMCP probe B", function() photo:applyDevelopPreset(preset, "LrMCP") end, { timeout = 15 })
out[#out + 1] = "B (two arguments): " .. tostring(rB) .. " gray now: " .. gray()
undo()

local rC = catalog:withWriteAccessDo("LrMCP probe C", function() photo:applyDevelopSettings(preset:getSetting()) end, { timeout = 15 })
out[#out + 1] = "C (applyDevelopSettings with the preset's own settings): " .. tostring(rC) .. " gray now: " .. gray()
undo()
out[#out + 1] = "gray after undo: " .. gray()
return table.concat(out, "\n")
