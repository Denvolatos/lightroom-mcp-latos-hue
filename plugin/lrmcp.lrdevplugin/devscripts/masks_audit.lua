-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: how many mask groups does each TEST photo hold, and what are they? Optionally clears them (CLEAR=true below
-- only for photos whose groups are all named "LrMCP test"). Written for cleaning up after the mask experiments.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"
local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then return "REFUSED: not the ceshi test catalog" end
local active = catalog:getTargetPhoto()
local lines = {}
for _, photo in ipairs(catalog:getAllPhotos()) do
	local g = photo:getDevelopSettings().MaskGroupBasedCorrections
	local names = {}
	if type(g) == "table" then
		for k, group in pairs(g) do names[#names + 1] = tostring(type(group) == "table" and group.CorrectionName or group) end
	end
	local isActive = active and active.localIdentifier == photo.localIdentifier
	lines[#lines + 1] = string.format("%s%s | groups=%d [%s]", LrPathUtils.leafName(photo:getRawMetadata("path")), isActive and " (ACTIVE)" or "", #names, table.concat(names, ";"))
end
return table.concat(lines, string.char(10))
