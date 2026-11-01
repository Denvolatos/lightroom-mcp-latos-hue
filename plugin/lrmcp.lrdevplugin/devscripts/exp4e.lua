-- Dev script (port of experiment 4e): for every photo of the TEST catalog (path contains "ceshi", max 8):
-- save all simple develop settings, make a REAL tiny change (Exposure2012 +0.01), revert it exactly, then report
-- which keys appeared/changed (Temperature/Tint?) and 1024px preview sizes before/after.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"
local LrExportSession = import "LrExportSession"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local catalog = LrApplication.activeCatalog()
if not tostring(catalog:getPath()):find("ceshi", 1, true) then
	return "REFUSED: active catalog is not the ceshi test catalog: " .. tostring(catalog:getPath())
end

local function exportSize(photo, label)
	local name = "exp4e_" .. label
	local path = LrPathUtils.child(ctx.dir, name .. ".jpg")
	if LrFileUtils.exists(path) then
		LrFileUtils.delete(path)
	end
	local settings = {
		LR_export_destinationType = "specificFolder", LR_export_destinationPathPrefix = ctx.dir,
		LR_export_useSubfolder = false, LR_reimportExportedPhoto = false, LR_collisionHandling = "overwrite",
		LR_renamingTokensOn = true, LR_tokens = "{{custom_token}}", LR_tokenCustomString = name,
		LR_extensionCase = "lowercase", LR_format = "JPEG", LR_jpeg_quality = 0.8, LR_export_colorSpace = "sRGB",
		LR_size_doConstrain = true, LR_size_resizeType = "longEdge", LR_size_maxHeight = 1024,
		LR_size_maxWidth = 1024, LR_size_units = "pixels", LR_size_doNotEnlarge = true, LR_size_resolution = 72,
		LR_size_resolutionUnits = "inch", LR_outputSharpeningOn = false, LR_minimizeEmbeddedMetadata = true,
		LR_useWatermark = false, LR_includeVideoFiles = false,
	}
	LrExportSession({ photosToExport = { photo }, exportSettings = settings }):doExportOnCurrentTask()
	local attrs = LrFileUtils.fileAttributes(path)
	return attrs and attrs.fileSize
end

local function simple(s)
	local out = {}
	for k, v in pairs(s) do
		if type(v) ~= "table" then
			out[k] = tostring(v)
		end
	end
	return out
end

local lines, done = {}, 0
for _, photo in ipairs(catalog:getAllPhotos()) do
	local path = photo:getRawMetadata("path")
	if done < 8 and path:find("ceshi", 1, true) then
		done = done + 1
		local name = LrPathUtils.leafName(path)
		local s0 = photo:getDevelopSettings()
		local before, e0 = simple(s0), s0.Exposure2012
		local ok0, size0 = LrTasks.pcall(exportSize, photo, name .. "_before")
		if type(e0) == "number" then
			local ok, err = LrTasks.pcall(function()
				catalog:withWriteAccessDo("LrMCP 4e change", function()
					photo:applyDevelopSettings({ Exposure2012 = e0 + 0.01 }, "LrMCP 4e change")
				end)
				catalog:withWriteAccessDo("LrMCP 4e revert", function()
					photo:applyDevelopSettings({ Exposure2012 = e0 }, "LrMCP 4e revert")
				end)
			end)
			local after = simple(photo:getDevelopSettings())
			local ok1, size1 = LrTasks.pcall(exportSize, photo, name .. "_after")
			local diffs = {}
			for k, v in pairs(after) do
				if before[k] ~= v then
					diffs[#diffs + 1] = string.format("%s: %s -> %s", k, tostring(before[k]), v)
				end
			end
			for k, v in pairs(before) do
				if after[k] == nil then
					diffs[#diffs + 1] = string.format("%s: %s -> (gone)", k, v)
				end
			end
			table.sort(diffs)
			lines[#lines + 1] = string.format("%s (%s) edit ok=%s err=%s | Temperature %s -> %s, Tint %s -> %s | preview %s -> %s | %d keys differ",
				name, tostring(photo:getRawMetadata("fileFormat")), tostring(ok), tostring(err), tostring(before.Temperature),
				tostring(after.Temperature), tostring(before.Tint), tostring(after.Tint), ok0 and tostring(size0) or "err",
				ok1 and tostring(size1) or "err", #diffs)
			for _, d in ipairs(diffs) do
				lines[#lines + 1] = "   DIFF " .. d
			end
		end
	end
end
return table.concat(lines, "\n")
