-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: write a mask to the ACTIVE photo by making another photo active for a moment. TEST catalog; clears afterwards.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"
local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then return "REFUSED: not the ceshi test catalog" end
local active = catalog:getTargetPhoto()
if not active then return "no selected photo" end
local selected = catalog:getTargetPhotos()
local lines = { "active: " .. LrPathUtils.leafName(active:getRawMetadata("path")) .. ", selected count " .. #selected }
local function write(photo, settings)
	LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP mask probe", function() photo:applyDevelopSettings(settings, "LrMCP mask probe") end)
	end)
end
local function stored(photo)
	local g = photo:getDevelopSettings().MaskGroupBasedCorrections
	return type(g) == "table" and next(g) ~= nil
end
local group = { CorrectionAmount = 1, CorrectionActive = true, CorrectionName = "LrMCP test", CorrectionSyncID = "11111111-2222-3333-4444-555555555555",
	LocalExposure2012 = -1.0, CorrectionMasks = { { What = "Mask/Gradient", MaskActive = true, MaskName = "Linear Gradient 1", MaskBlendMode = 0,
	MaskInverted = false, MaskSyncID = "66666666-7777-8888-9999-000000000000", MaskValue = 1, ZeroX = 0.5, ZeroY = 0.0, FullX = 0.5, FullY = 0.4 } } }
local other
for _, p in ipairs(catalog:getAllPhotos()) do
	if p.localIdentifier ~= active.localIdentifier then other = p break end
end
catalog:setSelectedPhotos(other, {})
LrTasks.sleep(0.5)
write(active, { MaskGroupBasedCorrections = {} })
catalog:setSelectedPhotos(active, {})
LrTasks.sleep(1)
lines[#lines + 1] = "cleared: stored=" .. tostring(stored(active))
return table.concat(lines, string.char(10))
