-- The whitelist of commands the Python server may ask for. v1.0: all read-only.
-- Every command returns a table (encoded to JSON by Bridge.lua) or raises fail("message") for the user.
-- Nothing here accepts a file path from the request; previews are written to a fixed folder.
local LrApplication = import "LrApplication"
local LrDate = import "LrDate"
local LrExportSession = import "LrExportSession"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"

local Json = require "Json.lua"
local Limits = require "Limits.lua"
local Version = require "Version.lua"

local M = {}

local previewDir = LrPathUtils.child(LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp"), "previews")
local MAX_LIST = 20
local previewCounter = 0
local MIN_EDGE, MAX_EDGE, DEFAULT_EDGE = 256, 2048, 1024

local function fail(message)
	error({ lrmcp = message }, 0)
end

local function photoFromRef(catalog, ref)
	if ref == nil or ref == "selected" then
		local photo = catalog:getTargetPhoto()
		if not photo then
			fail("Lightroom 里没有选中的照片，请先选中一张照片。")
		end
		return photo
	end
	local photo = catalog:findPhotoByUuid(ref)
	if not photo then
		fail("在当前目录里找不到这张照片：id 无效，或 Lightroom 现在打开的是另一个目录。")
	end
	return photo
end

local function formatted(photo, key)
	local v = photo:getFormattedMetadata(key)
	if v == nil or v == "" then
		return nil
	end
	return v
end

local function describe(photo)
	local dims = photo:getRawMetadata("dimensions") or {}
	local pick = photo:getRawMetadata("pickStatus")
	local make, model = formatted(photo, "cameraMake"), formatted(photo, "cameraModel")
	local camera = model
	if make and model and not model:find(make, 1, true) then
		camera = make .. " " .. model
	end
	return {
		id = photo:getRawMetadata("uuid"),
		name = LrPathUtils.leafName(photo:getRawMetadata("path") or ""),
		format = photo:getRawMetadata("fileFormat"),
		rating = photo:getRawMetadata("rating"),
		flag = (pick == 1 and "pick") or (pick == -1 and "reject") or "none",
		color_label = formatted(photo, "label"),
		width = dims.width,
		height = dims.height,
		is_cropped = photo:getRawMetadata("isCropped"),
		is_virtual_copy = photo:getRawMetadata("isVirtualCopy"),
		camera = camera,
		lens = formatted(photo, "lens"),
		iso = formatted(photo, "isoSpeedRating"),
		aperture = formatted(photo, "aperture"),
		shutter_speed = formatted(photo, "shutterSpeed"),
		focal_length = formatted(photo, "focalLength"),
		exposure_bias = formatted(photo, "exposureBias"),
		taken = formatted(photo, "dateTimeOriginal"),
	}
end

-- develop settings that v1.0 reports (names checked against Lightroom Classic 15.2)
local DEVELOP_KEYS = {
	"Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
	"Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation",
	"WhiteBalance", "Temperature", "Tint",
	"ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights",
	"Sharpness", "SharpenRadius", "SharpenDetail", "SharpenEdgeMasking",
	"LuminanceSmoothing", "LuminanceNoiseReductionDetail", "ColorNoiseReduction",
	"SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
	"SplitToningHighlightSaturation", "SplitToningBalance",
	"VignetteAmount", "PostCropVignetteAmount", "GrainAmount",
	"CropLeft", "CropTop", "CropRight", "CropBottom", "CropAngle",
	"ConvertToGrayscale", "ProcessVersion", "CameraProfile",
}
local COLORS = { "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta" }

local function hasEntries(t)
	return type(t) == "table" and next(t) ~= nil
end

function M.status()
	local v = LrApplication.versionTable()
	local catalog = LrApplication.activeCatalog()
	local path = catalog:getPath()
	local active = catalog:getTargetPhoto()
	return {
		lightroom_version = string.format("%d.%d.%d", v.major, v.minor, v.revision),
		lightroom_build = v.build_version,
		catalog = LrPathUtils.leafName(path),
		catalog_path = path,
		plugin_version = Version,
		has_selection = active ~= nil,
	}
end

function M.list_selected(params)
	local limit = math.max(1, math.min(tonumber(params.limit) or MAX_LIST, MAX_LIST))
	local catalog = LrApplication.activeCatalog()
	local active = catalog:getTargetPhoto()
	if not active then
		-- getTargetPhotos() would return the whole filmstrip when nothing is selected, so stop here.
		return { count = 0, photos = Json.array({}), note = "Lightroom 里没有选中的照片。" }
	end
	local selected = catalog:getTargetPhotos() or {}
	local photos = {}
	for i = 1, math.min(#selected, limit) do
		photos[#photos + 1] = describe(selected[i])
	end
	return {
		count = #selected,
		shown = #photos,
		active_id = active:getRawMetadata("uuid"),
		photos = Json.array(photos),
	}
end

function M.get_develop(params)
	local photo = photoFromRef(LrApplication.activeCatalog(), params.photo)
	local s = photo:getDevelopSettings()
	local settings = {}
	for _, key in ipairs(DEVELOP_KEYS) do
		if s[key] ~= nil then
			settings[key] = s[key]
		end
	end
	local hsl = {}
	for _, color in ipairs(COLORS) do
		hsl[color] = {
			hue = s["HueAdjustment" .. color],
			saturation = s["SaturationAdjustment" .. color],
			luminance = s["LuminanceAdjustment" .. color],
		}
	end
	local notes = {}
	if s.Temperature == nil then
		notes[#notes + 1] = "Temperature/Tint 暂时读不到（RAW 没编辑过时不显示，JPEG 没有开尔文值），不代表没有色温。"
	end
	return {
		photo = describe(photo),
		settings = settings,
		hsl = hsl,
		has_local_adjustments = hasEntries(s.MaskGroupBasedCorrections),
		notes = Json.array(notes),
	}
end

local function previewSettings(name, edge)
	return {
		LR_export_destinationType = "specificFolder",
		LR_export_destinationPathPrefix = previewDir,
		LR_export_useSubfolder = false,
		LR_reimportExportedPhoto = false,
		LR_collisionHandling = "overwrite",
		LR_renamingTokensOn = true,
		LR_tokens = "{{custom_token}}",
		LR_tokenCustomString = name,
		LR_extensionCase = "lowercase",
		LR_format = "JPEG",
		LR_jpeg_quality = 0.8,
		LR_export_colorSpace = "sRGB",
		LR_size_doConstrain = true,
		LR_size_resizeType = "longEdge",
		LR_size_maxHeight = edge,
		LR_size_maxWidth = edge,
		LR_size_units = "pixels",
		LR_size_doNotEnlarge = true,
		LR_size_resolution = 72,
		LR_size_resolutionUnits = "inch",
		LR_outputSharpeningOn = false,
		LR_minimizeEmbeddedMetadata = true,
		LR_useWatermark = false,
		LR_includeVideoFiles = false,
	}
end

function M.get_preview(params)
	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	local edge = math.max(MIN_EDGE, math.min(tonumber(params.long_edge) or DEFAULT_EDGE, MAX_EDGE))
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，暂不支持预览。")
	end
	LrFileUtils.createAllDirectories(previewDir)
	local uuid = tostring(photo:getRawMetadata("uuid")):gsub("[^%w]", ""):sub(1, 8)
	-- unique per call: two AI sessions may ask for a preview of the same photo within the same second, and a shared
	-- file name would let one session read the other's picture
	previewCounter = previewCounter + 1
	local name = string.format("p_%s_%d_%d", uuid, math.floor(LrDate.currentTime() * 1000), previewCounter)
	local path = LrPathUtils.child(previewDir, name .. ".jpg")
	if LrFileUtils.exists(path) then
		LrFileUtils.delete(path)
	end
	LrExportSession({ photosToExport = { photo }, exportSettings = previewSettings(name, edge) }):doExportOnCurrentTask()
	if not LrFileUtils.exists(path) then
		fail("Lightroom 没有生成预览文件（可能被导出设置或磁盘权限拦截）。")
	end
	local attrs = LrFileUtils.fileAttributes(path)
	return { path = path, name = LrPathUtils.leafName(photo:getRawMetadata("path") or ""), bytes = attrs and attrs.fileSize }
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Writing (v1.1). Every protection is checked here again; the plug-in never trusts the Python side.
-- ---------------------------------------------------------------------------------------------------------------------
local MAX_KEYS = 30
local VERIFY_TOLERANCE = 1e-3
local RESERVED = { photo = true, edit = true, restore = true, wb = true }
-- Changing Temperature/Tint also needs WhiteBalance = "Custom" (measured). Restoring writes the old label back; the
-- label travels as a token without spaces and only these values are accepted.
local WB_KEYS = { Temperature = true, Tint = true }
local WB_LABELS = {
	As_Shot = "As Shot", Auto = "Auto", Daylight = "Daylight", Cloudy = "Cloudy", Shade = "Shade",
	Tungsten = "Tungsten", Fluorescent = "Fluorescent", Flash = "Flash", Custom = "Custom",
}
local readonlyPath = LrPathUtils.child(LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp"), "readonly")

local function finiteNumber(text)
	local value = tonumber(text)
	if value == nil or value ~= value or value == math.huge or value == -math.huge then
		return nil
	end
	return value
end

-- Parameters: photo=<"selected"|uuid> edit=<id> [restore=1] <Slider>=<number> ...
-- restore=1 (writing back saved old values) skips only the step limit; whitelist and range still apply.
function M.set_develop(params)
	if LrFileUtils.exists(readonlyPath) then
		fail("只读模式已开启（" .. readonlyPath .. " 存在），不允许修改照片。")
	end
	local editId = params.edit
	if not editId or not editId:match("^[%w%-]+$") then
		fail("缺少或不合法的修改编号。")
	end
	local restoring = params.restore == "1"

	local changes, count = {}, 0
	for key, text in pairs(params) do
		if not RESERVED[key] then
			local limit = Limits[key]
			if not limit then
				fail("不允许修改这个参数：" .. tostring(key))
			end
			local value = finiteNumber(text)
			if not value then
				fail(key .. " 的值不是有效数字：" .. tostring(text))
			end
			if value < limit[1] or value > limit[2] then
				fail(string.format("%s 的取值范围是 %g 到 %g，收到 %g。", key, limit[1], limit[2], value))
			end
			changes[key] = value
			count = count + 1
		end
	end
	if count == 0 then
		fail("没有要修改的参数。")
	end
	if count > MAX_KEYS then
		fail(string.format("一次最多改 %d 个参数，收到 %d 个。", MAX_KEYS, count))
	end

	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，不支持修改。")
	end

	-- read the current values and check the step size BEFORE writing anything
	local current = photo:getDevelopSettings()
	local before = {}
	for key, value in pairs(changes) do
		local now = current[key]
		if type(now) ~= "number" then
			if WB_KEYS[key] then
				fail("这张照片读不到色温/色调的当前值（JPEG 没有开尔文值；没编辑过的 RAW 也可能读不到，先在 Lightroom 里对它做任意一次编辑再试）。照片没有改动。")
			end
			fail("读不到 " .. key .. " 的当前值，已取消修改，照片没有改动。")
		end
		before[key] = now
		local step = Limits[key][3]
		if not restoring and math.abs(value - now) > step + 1e-9 then
			fail(string.format("%s 当前是 %g，目标 %g，单次最多改 ±%g。请分几次改，每次改完用 lr_get_preview 看一眼效果。",
				key, now, value, step))
		end
	end

	local toWrite, beforeWb = changes, nil
	if changes.Temperature ~= nil or changes.Tint ~= nil then
		beforeWb = current.WhiteBalance
		toWrite = {}
		for key, value in pairs(changes) do
			toWrite[key] = value
		end
		toWrite.WhiteBalance = (restoring and WB_LABELS[params.wb]) or "Custom"
	end
	local result = catalog:withWriteAccessDo("LrMCP " .. editId, function()
		photo:applyDevelopSettings(toWrite, "LrMCP " .. editId)
	end, { timeout = 15 })
	if result ~= "executed" then
		fail("Lightroom 现在不能写入（可能正忙），没有做任何修改，请稍后再试。")
	end

	-- read back after the write gate and report what Lightroom really stored
	local stored = photo:getDevelopSettings()
	local after, verified = {}, true
	for key, value in pairs(changes) do
		after[key] = stored[key]
		if type(stored[key]) ~= "number" or math.abs(stored[key] - value) > VERIFY_TOLERANCE then
			verified = false
		end
	end
	return { before = before, before_wb = beforeWb, after = after, verified = verified, photo = describe(photo) }
end

local COMMANDS = {
	status = M.status,
	list_selected = M.list_selected,
	get_develop = M.get_develop,
	get_preview = M.get_preview,
	set_develop = M.set_develop,
}

function M.run(command, params)
	local handler = COMMANDS[command]
	if not handler then
		fail("插件不认识这个命令：" .. tostring(command))
	end
	return handler(params or {})
end

return M
