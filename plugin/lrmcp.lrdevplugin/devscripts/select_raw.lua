-- Dev script: select the first RAW photo of the TEST catalog (changes only Lightroom's selection, not any photo).
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrPathUtils = import "LrPathUtils"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
for _, photo in ipairs(catalog:getAllPhotos()) do
	if photo:getRawMetadata("fileFormat") == "RAW" then
		catalog:setSelectedPhotos(photo, {})
		return "selected " .. LrPathUtils.leafName(photo:getRawMetadata("path"))
	end
end
return "no RAW in the catalog"
