-- Dev script: select three photos of the TEST catalog: the first two RAW and the first JPEG (any file names).
-- Changes only Lightroom's selection, not any photo.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: not the ceshi test catalog"
end
local raws, jpegs = {}, {}
for _, photo in ipairs(catalog:getAllPhotos()) do
	local format = photo:getRawMetadata("fileFormat")
	if format == "RAW" and #raws < 2 then raws[#raws + 1] = photo end
	if format == "JPG" and #jpegs < 1 then jpegs[#jpegs + 1] = photo end
end
if #raws < 2 or #jpegs < 1 then
	return "need 2 RAW and 1 JPEG, found " .. #raws .. " RAW and " .. #jpegs .. " JPEG"
end
catalog:setSelectedPhotos(raws[1], { raws[2], jpegs[1] })
return "selected 3 photos"
