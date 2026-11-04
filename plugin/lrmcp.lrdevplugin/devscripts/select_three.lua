-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: select three photos of the TEST catalog (two RAW, one JPEG). Changes only Lightroom's selection.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local wanted = { ["DSC08151.ARW"] = true, ["DSC08206.ARW"] = true, ["DSC08205.JPG"] = true }
local found = {}
for _, photo in ipairs(catalog:getAllPhotos()) do
	if wanted[LrPathUtils.leafName(photo:getRawMetadata("path"))] then
		found[#found + 1] = photo
	end
end
if #found < 3 then
	return "expected 3 photos, found " .. #found
end
catalog:setSelectedPhotos(found[1], { found[2], found[3] })
return "selected " .. #found .. " photos"
