-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: which TEST photos accept a mask written through applyDevelopSettings, and what do they have in common?
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"
local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then return "REFUSED: not the ceshi test catalog" end
local function write(photo, settings)
	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo("LrMCP mask probe", function() photo:applyDevelopSettings(settings, "LrMCP mask probe") end)
	end)
	return ok and "ok" or ("ERROR " .. tostring(err))
end
local group = { CorrectionAmount = 1, CorrectionActive = true, CorrectionName = "LrMCP test", CorrectionSyncID = "11111111-2222-3333-4444-555555555555",
	LocalExposure2012 = -1.0, CorrectionMasks = { { What = "Mask/Gradient", MaskActive = true, MaskName = "Linear Gradient 1", MaskBlendMode = 0,
	MaskInverted = false, MaskSyncID = "66666666-7777-8888-9999-000000000000", MaskValue = 1, ZeroX = 0.5, ZeroY = 0.0, FullX = 0.5, FullY = 0.4 } } }
local lines = {}
for _, photo in ipairs(catalog:getAllPhotos()) do
	local name = LrPathUtils.leafName(photo:getRawMetadata("path"))
	local s = photo:getDevelopSettings()
	local extras = {}
	for _, k in ipairs({ "DepthMapInfo", "LensBlur", "GrainSeed", "Look", "ProcessVersion", "HasSettings" }) do
		extras[#extras + 1] = k .. "=" .. (s[k] == nil and "nil" or (type(s[k]) == "table" and "table" or tostring(s[k])))
	end
	local w = write(photo, { MaskGroupBasedCorrections = { group } })
	local g = photo:getDevelopSettings().MaskGroupBasedCorrections
	lines[#lines + 1] = string.format("%s | write=%s | stored=%s | %s", name, w, tostring(type(g) == "table" and next(g) ~= nil), table.concat(extras, " "))
	write(photo, { MaskGroupBasedCorrections = {} })
end
return table.concat(lines, "\n")
