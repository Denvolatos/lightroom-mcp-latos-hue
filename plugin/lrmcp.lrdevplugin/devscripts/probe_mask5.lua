-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: does the SELECTED photo accept a mask later (async), or never? TEST catalog; clears afterwards.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"
local LrApplicationView = import "LrApplicationView"
local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then return "REFUSED: not the ceshi test catalog" end
local photo = catalog:getTargetPhoto()
if not photo then return "no selected photo" end
local function write(settings)
	LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP mask probe", function() photo:applyDevelopSettings(settings, "LrMCP mask probe") end)
	end)
end
local function stored()
	local g = photo:getDevelopSettings().MaskGroupBasedCorrections
	return type(g) == "table" and next(g) ~= nil
end
local group = { CorrectionAmount = 1, CorrectionActive = true, CorrectionName = "LrMCP test", CorrectionSyncID = "11111111-2222-3333-4444-555555555555",
	LocalExposure2012 = -1.0, CorrectionMasks = { { What = "Mask/Gradient", MaskActive = true, MaskName = "Linear Gradient 1", MaskBlendMode = 0,
	MaskInverted = false, MaskSyncID = "66666666-7777-8888-9999-000000000000", MaskValue = 1, ZeroX = 0.5, ZeroY = 0.0, FullX = 0.5, FullY = 0.4 } } }
local lines = { "selected photo: " .. LrPathUtils.leafName(photo:getRawMetadata("path")), "module now: " .. tostring(LrApplicationView.getCurrentModuleName()) }
local function attempt(label)
	write({ MaskGroupBasedCorrections = { group } })
	LrTasks.sleep(1)
	lines[#lines + 1] = label .. ": stored=" .. tostring(stored())
	write({ MaskGroupBasedCorrections = {} })
end
attempt("in current module")
LrApplicationView.switchToModule("develop")
LrTasks.sleep(2)
lines[#lines + 1] = "module now: " .. tostring(LrApplicationView.getCurrentModuleName())
attempt("in Develop module")
LrApplicationView.switchToModule("library")
LrTasks.sleep(2)
attempt("back in Library module")
return table.concat(lines, "\n")
