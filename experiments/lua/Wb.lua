-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Menu item: "LrMCP: White balance test (experiment 4c)".
-- Select the TEST photo (DSC08238.ARW). Finds out whether writing WhiteBalance="As Shot" alone restores the
-- rendering (the Temperature/Tint values stay stale), by exporting a 1024px preview after each state and
-- comparing file sizes with the pristine preview (286204 bytes). Ends with As Shot + 5550/13 written explicitly.
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrExportSession = import "LrExportSession"
local LrFileUtils = import "LrFileUtils"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrTasks = import "LrTasks"

local logger = LrLogger("LrMcpExp4c")
logger:enable("logfile")
local function log(text)
	logger:info(text)
end

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")

local function exportSize(photo, label)
	local name = "exp4c_" .. label
	local path = LrPathUtils.child(dir, name .. ".jpg")
	if LrFileUtils.exists(path) then
		LrFileUtils.delete(path)
	end
	local settings = {
		LR_export_destinationType = "specificFolder", LR_export_destinationPathPrefix = dir,
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

LrTasks.startAsyncTask(function()
	local catalog = LrApplication.activeCatalog()
	local photo = catalog:getTargetPhoto()
	if not photo or not photo:getRawMetadata("path"):find("ceshi", 1, true) then
		LrDialogs.message("LrMCP experiment 4c", "Select the test photo (in the 'ceshi' folder) first.", "info")
		return
	end
	log("=== experiment 4c on " .. photo:getRawMetadata("path") .. " ===")

	local function state()
		local s = photo:getDevelopSettings()
		return string.format("WhiteBalance=%s Temperature=%s Tint=%s", tostring(s.WhiteBalance), tostring(s.Temperature),
			tostring(s.Tint))
	end
	local function apply(settings, name)
		local ok, err = LrTasks.pcall(function()
			catalog:withWriteAccessDo(name, function()
				photo:applyDevelopSettings(settings, name)
			end)
		end)
		if not ok then
			log("apply FAILED: " .. tostring(err))
		end
	end
	local function measure(label)
		local ok, size = LrTasks.pcall(function()
			return exportSize(photo, label)
		end)
		log(string.format("[%s] %s -> preview size=%s", label, state(), ok and tostring(size) or ("export error " .. tostring(size))))
	end

	measure("1_current")
	apply({ WhiteBalance = "As Shot", Temperature = 5550, Tint = 13 }, "LrMCP 4c explicit")
	measure("2_explicit_asshot_5550_13")
	apply({ WhiteBalance = "Custom", Temperature = 3000, Tint = 0 }, "LrMCP 4c custom 3000")
	measure("3_custom_3000")
	apply({ WhiteBalance = "As Shot" }, "LrMCP 4c asshot only")
	measure("4_asshot_only_after_3000")
	apply({ WhiteBalance = "As Shot", Temperature = 5550, Tint = 13 }, "LrMCP 4c final")
	measure("5_final_explicit")

	LrDialogs.message("LrMCP experiment 4c", "Done. See LrMcpExp4c.log.", "info")
end)
