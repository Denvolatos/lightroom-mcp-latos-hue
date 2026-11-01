-- Dev script: select one photo of the TEST catalog (changes only Lightroom's selection, not any photo).
-- The photo is the first one whose file name contains "238" (a RAW in the ceshi folder).
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
for _, photo in ipairs(catalog:getAllPhotos()) do
	local name = LrPathUtils.leafName(photo:getRawMetadata("path"))
	if name:find("238", 1, true) then
		catalog:setSelectedPhotos(photo, {})
		return "selected " .. name
	end
end
return "no photo with 238 in its name"
