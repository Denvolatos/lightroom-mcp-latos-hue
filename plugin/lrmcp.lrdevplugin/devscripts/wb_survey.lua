-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script (READ ONLY): what white balance values does Lightroom report for each photo of the TEST catalog?
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local lines = {}
for _, photo in ipairs(catalog:getAllPhotos()) do
	local s = photo:getDevelopSettings()
	lines[#lines + 1] = string.format("%s | %s | WB=%s Temp=%s Tint=%s | ProcessVersion=%s | hasAdjustments=%s",
		LrPathUtils.leafName(photo:getRawMetadata("path")), tostring(photo:getRawMetadata("fileFormat")),
		tostring(s.WhiteBalance), tostring(s.Temperature), tostring(s.Tint), tostring(s.ProcessVersion),
		tostring(photo:getDevelopSettings().HasSettings))
end
return table.concat(lines, "\n")
