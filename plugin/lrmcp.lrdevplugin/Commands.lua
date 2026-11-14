-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- The whitelist of commands the Python server may ask for. v1.0: all read-only.
-- Every command returns a table (encoded to JSON by Bridge.lua) or raises fail("message") for the user.
-- Nothing here accepts a file path from the request; previews are written to a fixed folder.
local LrApplication = import "LrApplication"
local LrDate = import "LrDate"
local LrExportSession = import "LrExportSession"
local LrExportSettings = import "LrExportSettings"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"
local LrStringUtils = import "LrStringUtils"
local LrTasks = import "LrTasks"

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

-- Lua's character classes (%c, %w, %a, %s ...) and string.lower/upper follow the C locale of the process. With a western
-- code page (cp1252) the bytes 0x80-0xFF count as letters, control or space characters, so the bytes of UTF-8 text (Chinese
-- paths and names) would be refused, cut apart or changed. Only explicit ASCII ranges are used here.
local CONTROL_CHARS = "[%z\1-\31\127]" -- ASCII control characters: 0x00-0x1F and 0x7F
local ASCII_LOWER = {}
for code = 65, 90 do
	ASCII_LOWER[string.char(code)] = string.char(code + 32)
end
local function asciiLower(text)
	return (text:gsub("[A-Z]", ASCII_LOWER))
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
	"LuminanceNoiseReductionContrast", "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness",
	"PostCropVignetteMidpoint", "PostCropVignetteFeather", "PostCropVignetteRoundness", "PostCropVignetteHighlightContrast",
	"GrainSize", "GrainFrequency", "VignetteMidpoint", "DefringePurpleAmount", "DefringeGreenAmount",
	"ColorGradeShadowLum", "ColorGradeHighlightLum", "ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeMidtoneLum",
	"ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum", "ColorGradeBlending",
	"ShadowTint", "RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation",
	"ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue",
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

-- name: file name without extension; dir: destination folder; edge: pixels of the long side (0 = original size)
-- tiff: nil for JPEG (unchanged); or { bitDepth = 8|16 } for TIFF (sRGB, lossless ZIP compression, no JPEG quality)
local function exportSettings(name, dir, edge, quality, minimalMetadata, tiff)
	local settings = {
		LR_export_destinationType = "specificFolder",
		LR_export_destinationPathPrefix = dir,
		LR_export_useSubfolder = false,
		LR_reimportExportedPhoto = false,
		LR_collisionHandling = "overwrite", -- callers pick a free name themselves (previews are unique, exports check)
		LR_renamingTokensOn = true,
		LR_tokens = "{{custom_token}}",
		LR_tokenCustomString = name,
		LR_extensionCase = "lowercase",
		LR_format = "JPEG",
		LR_jpeg_quality = quality,
		LR_export_colorSpace = "sRGB",
		LR_size_doConstrain = edge > 0,
		LR_size_units = "pixels",
		LR_size_doNotEnlarge = true,
		LR_size_resolution = 72,
		LR_size_resolutionUnits = "inch",
		LR_outputSharpeningOn = false,
		LR_minimizeEmbeddedMetadata = minimalMetadata,
		LR_useWatermark = false,
		LR_includeVideoFiles = false,
	}
	if tiff then
		-- Verified on real Lightroom 15.2 (2026-11-03: 16-bit and 8-bit files, ZIP compression, ICC profile embedded): the SDK documents only LR_format = 'TIFF'; the two keys below are the ones Lightroom
		-- itself writes for TIFF export presets and are not listed in the SDK docs
		settings.LR_format = "TIFF"
		settings.LR_jpeg_quality = nil
		settings.LR_export_bitDepth = tiff.bitDepth
		settings.LR_tiff_compressionMethod = "compressionMethod_ZIP"
	end
	if edge > 0 then
		settings.LR_size_resizeType = "longEdge"
		settings.LR_size_maxHeight = edge
		settings.LR_size_maxWidth = edge
	end
	return settings
end

local function previewSettings(name, edge)
	return exportSettings(name, previewDir, edge, 0.8, true)
end

function M.get_preview(params)
	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	local edge = math.max(MIN_EDGE, math.min(tonumber(params.long_edge) or DEFAULT_EDGE, MAX_EDGE))
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，暂不支持预览。")
	end
	LrFileUtils.createAllDirectories(previewDir)
	local uuid = tostring(photo:getRawMetadata("uuid")):gsub("[^A-Za-z0-9]", ""):sub(1, 8)
	-- unique per call: two AI sessions may ask for a preview of the same photo within the same second, and a shared
	-- file name would let one session read the other's picture
	previewCounter = previewCounter + 1
	local name = string.format("p_%s_%.0f_%d", uuid, math.floor(LrDate.currentTime() * 1000), previewCounter)
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
-- Point curves travel as "x1,y1,x2,y2,..." (0..255). Same rules as the Python side; the deviation limit is the "step".
local CURVE_KEYS = { ToneCurvePV2012 = true, ToneCurvePV2012Red = true, ToneCurvePV2012Green = true, ToneCurvePV2012Blue = true }
local MAX_CURVE_POINTS = 16
local MAX_CURVE_DEVIATION = 90

local function parseCurve(key, text, restoring)
	local flat = {}
	for part in tostring(text):gmatch("[^,]+") do
		local n = tonumber(part)
		if n == nil or n ~= n or n < 0 or n > 255 then
			fail(key .. " 里的坐标必须是 0 到 255 的数字：" .. tostring(part))
		end
		flat[#flat + 1] = n
	end
	local points = #flat / 2
	if #flat == 0 or #flat % 2 ~= 0 or points < 2 or points > MAX_CURVE_POINTS then
		fail(string.format("%s 需要 2 到 %d 个点（x,y 成对），收到 %g 个数。", key, MAX_CURVE_POINTS, #flat))
	end
	for i = 2, points do
		if flat[2 * i - 1] <= flat[2 * i - 3] then
			fail(key .. " 的点必须按 x 从小到大排列，且 x 不能重复。")
		end
	end
	if not restoring then
		if flat[1] ~= 0 or flat[#flat - 1] ~= 255 then
			fail(key .. " 的第一个点的 x 必须是 0，最后一个点的 x 必须是 255。")
		end
		for i = 2, points do
			if flat[2 * i] < flat[2 * i - 2] then
				fail(key .. " 的 y 不能往回走（不支持反相曲线）。")
			end
		end
		for i = 1, points do
			if math.abs(flat[2 * i] - flat[2 * i - 1]) > MAX_CURVE_DEVIATION then
				fail(string.format("%s 的每个点离直线（y = x）最多 %d，一次改太大了。", key, MAX_CURVE_DEVIATION))
			end
		end
	end
	return flat
end

local function sameNumbers(a, b)
	if type(a) ~= "table" or type(b) ~= "table" or #a ~= #b then
		return false
	end
	for i = 1, #a do
		if type(b[i]) ~= "number" or math.abs(a[i] - b[i]) > 1e-3 then
			return false
		end
	end
	return true
end
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
	if not editId or not editId:match("^[A-Za-z0-9%-]+$") then
		fail("缺少或不合法的修改编号。")
	end
	local restoring = params.restore == "1"

	local changes, count = {}, 0
	for key, text in pairs(params) do
		if not RESERVED[key] then
			if CURVE_KEYS[key] then
				changes[key] = parseCurve(key, text, restoring)
				count = count + 1
			else
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
		if CURVE_KEYS[key] then
			if type(now) ~= "table" or #now < 4 then
				fail("读不到 " .. key .. " 的当前曲线，已取消修改，照片没有改动。")
			end
			local copy = {}
			for i = 1, #now do
				copy[i] = now[i]
			end
			before[key] = copy
		else
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
	end

	if not restoring then
		local cropKeys = { "CropLeft", "CropTop", "CropRight", "CropBottom" }
		local touched = false
		for _, k in ipairs(cropKeys) do
			if changes[k] ~= nil then touched = true end
		end
		if touched then
			local v = {}
			for _, k in ipairs(cropKeys) do
				v[k] = changes[k] ~= nil and changes[k] or current[k]
				if type(v[k]) ~= "number" then
					fail("读不到这张照片当前的裁剪值，已取消修改，照片没有改动。")
				end
			end
			if v.CropRight - v.CropLeft < 0.1 - 1e-9 or v.CropBottom - v.CropTop < 0.1 - 1e-9 then
				fail(string.format("裁剪后的宽和高都必须至少保留原图的 10%%，并且 CropLeft < CropRight、CropTop < CropBottom。改完会是：左 %g 右 %g 上 %g 下 %g。",
					v.CropLeft, v.CropRight, v.CropTop, v.CropBottom))
			end
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
		if CURVE_KEYS[key] then
			if not sameNumbers(value, stored[key]) then
				verified = false
			end
		elseif type(stored[key]) ~= "number" or math.abs(stored[key] - value) > VERIFY_TOLERANCE then
			verified = false
		end
	end
	return { before = before, before_wb = beforeWb, after = after, verified = verified, photo = describe(photo) }
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Develop presets (v0.9). A preset can touch many settings, including ones this project does not otherwise write
-- (looks, camera profiles, black & white mixer...). It is applied by Lightroom itself; undo works by writing back the old
-- values of every setting that changed, which the server saved first (snapshot) and gets back from apply_preset.
-- Presets that carry masks / AI local adjustments are refused.
-- ---------------------------------------------------------------------------------------------------------------------
local function deepcopy(v)
	if type(v) ~= "table" then
		return v
	end
	local c = {}
	for k, x in pairs(v) do
		c[k] = deepcopy(x)
	end
	return c
end

local function serialize(v)
	if type(v) ~= "table" then
		return type(v) == "string" and string.format("%q", v) or tostring(v)
	end
	local keys = {}
	for k in pairs(v) do
		keys[#keys + 1] = k
	end
	table.sort(keys, function(a, b)
		return tostring(a) < tostring(b)
	end)
	local parts = {}
	for _, k in ipairs(keys) do
		parts[#parts + 1] = tostring(k) .. "=" .. serialize(v[k])
	end
	return "{" .. table.concat(parts, ",") .. "}"
end

local function sameValue(a, b)
	if type(a) == "number" and type(b) == "number" then
		return math.abs(a - b) <= 1e-6
	end
	if type(a) ~= type(b) then
		return false
	end
	if type(a) == "table" then
		return serialize(a) == serialize(b)
	end
	return a == b
end

local function countNodes(v)
	if type(v) ~= "table" then
		return 1
	end
	local n = 1
	for _, x in pairs(v) do
		n = n + countNodes(x)
	end
	return n
end

local function findPreset(uuid)
	for _, folder in ipairs(LrApplication.developPresetFolders()) do
		for _, preset in ipairs(folder:getDevelopPresets()) do
			if preset:getUuid() == uuid then
				return preset, folder
			end
		end
	end
end

function M.list_presets(params)
	local query = params.query and params.query ~= "" and asciiLower(params.query) or nil
	local limit = math.max(1, math.min(tonumber(params.limit) or 30, 50))
	local rows, total, matched = {}, 0, 0
	for _, folder in ipairs(LrApplication.developPresetFolders()) do
		local folderName = tostring(folder:getName())
		for _, preset in ipairs(folder:getDevelopPresets()) do
			total = total + 1
			local name = tostring(preset:getName())
			if not query or asciiLower(name):find(query, 1, true) or asciiLower(folderName):find(query, 1, true) then
				matched = matched + 1
				if #rows < limit then
					local s = preset:getSetting() or {}
					rows[#rows + 1] = {
						id = preset:getUuid(),
						name = name,
						folder = folderName,
						has_masks = hasEntries(s.MaskGroupBasedCorrections),
					}
				end
			end
		end
	end
	return { total = total, matched = matched, shown = #rows, presets = Json.array(rows) }
end

-- All develop settings of a photo (read only), so the server can save them before a preset is applied.
function M.snapshot(params)
	local photo = photoFromRef(LrApplication.activeCatalog(), params.photo)
	local all = photo:getDevelopSettings()
	local settings = deepcopy(all)
	settings.MaskGroupBasedCorrections = nil -- local adjustments are not part of what presets may change here
	return { photo = describe(photo), settings = settings, has_local_adjustments = hasEntries(all.MaskGroupBasedCorrections) }
end

-- Parameters: photo=<"selected"|uuid> edit=<id> preset=<preset uuid>
function M.apply_preset(params)
	if LrFileUtils.exists(readonlyPath) then
		fail("只读模式已开启（" .. readonlyPath .. " 存在），不允许修改照片。")
	end
	local editId = params.edit
	if not editId or not editId:match("^[A-Za-z0-9%-]+$") then
		fail("缺少或不合法的修改编号。")
	end
	local presetId = params.preset
	if not presetId or not presetId:match("^[A-Za-z0-9%-]+$") then
		fail("缺少或不合法的预设 id（用 lr_list_presets 查）。")
	end
	local preset = findPreset(presetId)
	if not preset then
		fail("找不到这个预设：id 无效。用 lr_list_presets 查。")
	end
	if hasEntries((preset:getSetting() or {}).MaskGroupBasedCorrections) then
		fail("这个预设带有蒙版/局部调整（自适应预设），暂不支持套用，也没法安全还原。请让用户在 Lightroom 里自己套用。")
	end
	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，不支持修改。")
	end
	if hasEntries(photo:getDevelopSettings().MaskGroupBasedCorrections) then
		fail("这张照片已经有蒙版/局部调整，套预设可能影响它们且无法安全还原，已取消。")
	end

	local before = deepcopy(photo:getDevelopSettings())
	local result = catalog:withWriteAccessDo("LrMCP " .. editId, function()
		photo:applyDevelopPreset(preset)
	end, { timeout = 15 })
	if result ~= "executed" then
		fail("Lightroom 现在不能写入（可能正忙），没有做任何修改，请稍后再试。")
	end
	local after = photo:getDevelopSettings()

	local keys, seen = {}, {}
	for k in pairs(before) do
		seen[k] = true
	end
	for k in pairs(after) do
		seen[k] = true
	end
	for k in pairs(seen) do
		if k ~= "MaskGroupBasedCorrections" and serialize(before[k]) ~= serialize(after[k]) then
			keys[#keys + 1] = k
		end
	end
	table.sort(keys)
	local changes, tables, newKeys, oldValues = {}, {}, {}, {}
	for _, k in ipairs(keys) do
		if before[k] == nil then
			newKeys[#newKeys + 1] = k
		else
			oldValues[k] = deepcopy(before[k])
		end
		if type(after[k]) == "table" or type(before[k]) == "table" then
			tables[#tables + 1] = k
		else
			changes[k] = { before = before[k], after = after[k] }
		end
	end
	return {
		preset = preset:getName(),
		changed_keys = Json.array(keys),
		changes = changes,
		tables_changed = Json.array(tables),
		new_keys = Json.array(newKeys),
		before = oldValues,
		photo = describe(photo),
	}
end

-- Writes back old values (JSON in the percent-encoded parameter "blob"). Only keys that exist now, with the same type,
-- inside the known ranges, and never local adjustments.
-- Parameters: photo=<"selected"|uuid> edit=<id> blob=<percent-encoded JSON object>
function M.restore_settings(params)
	if LrFileUtils.exists(readonlyPath) then
		fail("只读模式已开启（" .. readonlyPath .. " 存在），不允许修改照片。")
	end
	local editId = params.edit
	if not editId or not editId:match("^[A-Za-z0-9%-]+$") then
		fail("缺少或不合法的修改编号。")
	end
	local blob = params.blob
	if not blob or blob == "" or #blob > 150000 then
		fail("缺少要还原的数据，或数据太大。")
	end
	local text = blob:gsub("%%(%x%x)", function(h)
		return string.char(tonumber(h, 16))
	end)
	local values = Json.decode(text)
	if type(values) ~= "table" or next(values) == nil then
		fail("没有要还原的内容。")
	end
	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，不支持修改。")
	end
	local current = photo:getDevelopSettings()
	local count = 0
	for key, value in pairs(values) do
		count = count + 1
		if count > 300 then
			fail("要还原的项目太多。")
		end
		if type(key) ~= "string" or not key:match("^[A-Za-z0-9_]+$") then
			fail("不合法的参数名。")
		end
		if key == "MaskGroupBasedCorrections" then
			fail("不允许通过这个途径改蒙版/局部调整。")
		end
		local now = current[key]
		if now == nil then
			fail("照片当前没有这个设置，没法写回：" .. key)
		end
		if type(now) ~= type(value) then
			fail("类型对不上，已取消还原：" .. key)
		end
		if type(value) == "number" then
			if value ~= value or value == math.huge or value == -math.huge then
				fail(key .. " 的值不是有效数字。")
			end
			local limit = Limits[key]
			if limit and (value < limit[1] or value > limit[2]) then
				fail(string.format("%s 的取值范围是 %g 到 %g，收到 %g。", key, limit[1], limit[2], value))
			end
		elseif type(value) == "string" then
			if #value > 200 then
				fail(key .. " 的文字太长。")
			end
		elseif type(value) == "table" then
			if countNodes(value) > 2000 then
				fail(key .. " 的内容太大。")
			end
		end
	end
	local result = catalog:withWriteAccessDo("LrMCP " .. editId, function()
		photo:applyDevelopSettings(values, "LrMCP " .. editId)
	end, { timeout = 15 })
	if result ~= "executed" then
		fail("Lightroom 现在不能写入（可能正忙），没有做任何修改，请稍后再试。")
	end
	local stored = photo:getDevelopSettings()
	local verified, after, before = true, {}, {}
	for key, value in pairs(values) do
		if not sameValue(value, stored[key]) then
			verified = false
		end
		if type(value) ~= "table" then
			after[key] = stored[key]
		end
		if type(current[key]) ~= "table" then
			before[key] = current[key]
		end
	end
	return { before = before, after = after, verified = verified, restored = count, photo = describe(photo) }
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Catalog information (v0.11): rating, flag, colour label, title, caption, keywords. These are not develop settings; they
-- live in the catalog (and in XMP when Lightroom is set to write it). Every change is reversible: the server saves the
-- old values and restores them by calling set_metadata again.
-- ---------------------------------------------------------------------------------------------------------------------
local FLAG_TO_PICK = { pick = 1, none = 0, reject = -1 }
local PICK_TO_FLAG = { [1] = "pick", [0] = "none", [-1] = "reject" }
local LABELS = { red = true, yellow = true, green = true, blue = true, purple = true, none = true }
local MAX_TITLE, MAX_CAPTION, MAX_KEYWORD, MAX_KEYWORDS_PER_CALL = 200, 1000, 60, 10

local function urlDecode(text)
	return (text:gsub("%%(%x%x)", function(h)
		return string.char(tonumber(h, 16))
	end))
end

local function hasControlChars(text)
	return text:find(CONTROL_CHARS) ~= nil
end

local function keywordNames(photo)
	local names = {}
	for _, keyword in ipairs(photo:getRawMetadata("keywords") or {}) do
		names[#names + 1] = keyword:getName()
	end
	table.sort(names)
	return names
end

local function readMetadata(photo)
	local label = photo:getRawMetadata("colorNameForLabel")
	return {
		rating = photo:getRawMetadata("rating") or 0,
		flag = PICK_TO_FLAG[photo:getRawMetadata("pickStatus")] or "none",
		-- measured: Lightroom reports "no colour label" as "gray"
		color_label = (label == nil or label == "" or label == "gray" or label == "grey") and "none" or label,
		title = photo:getFormattedMetadata("title") or "",
		caption = photo:getFormattedMetadata("caption") or "",
		keywords = Json.array(keywordNames(photo)),
	}
end

function M.get_metadata(params)
	local photo = photoFromRef(LrApplication.activeCatalog(), params.photo)
	return { photo = describe(photo), metadata = readMetadata(photo) }
end

local function splitKeywords(text, what)
	local names = {}
	for part in tostring(text):gmatch("[^,]+") do
		local name = urlDecode(part)
		if name == "" or #name > MAX_KEYWORD or hasControlChars(name) then
			fail(what .. " 里有不合法的关键词（不能为空、不能超过 " .. MAX_KEYWORD .. " 个字符、不能含控制字符）。")
		end
		names[#names + 1] = name
	end
	if #names == 0 then
		fail(what .. " 是空的。")
	end
	if #names > MAX_KEYWORDS_PER_CALL then
		fail(string.format("一次最多处理 %d 个关键词。", MAX_KEYWORDS_PER_CALL))
	end
	return names
end

-- Parameters: photo=<"selected"|uuid> edit=<id> and any of: rating=0..5 flag=pick|none|reject color=<label>
-- title=<percent-encoded> caption=<percent-encoded> add_kw=<name,name> remove_kw=<name,name> (names percent-encoded)
function M.set_metadata(params)
	if LrFileUtils.exists(readonlyPath) then
		fail("只读模式已开启（" .. readonlyPath .. " 存在），不允许修改照片。")
	end
	local editId = params.edit
	if not editId or not editId:match("^[A-Za-z0-9%-]+$") then
		fail("缺少或不合法的修改编号。")
	end
	local rating, flag, color, title, caption, addNames, removeNames
	if params.rating ~= nil then
		rating = finiteNumber(params.rating)
		if not rating or rating ~= math.floor(rating) or rating < 0 or rating > 5 then
			fail("星级必须是 0 到 5 的整数。")
		end
	end
	if params.flag ~= nil then
		flag = FLAG_TO_PICK[params.flag]
		if flag == nil then
			fail("旗标必须是 pick、none 或 reject。")
		end
	end
	if params.color ~= nil then
		color = asciiLower(params.color)
		if not LABELS[color] then
			fail("颜色标签必须是 red、yellow、green、blue、purple 或 none。")
		end
	end
	if params.title ~= nil then
		title = urlDecode(params.title)
		if #title > MAX_TITLE or hasControlChars(title) then
			fail("标题太长或含控制字符。")
		end
	end
	if params.caption ~= nil then
		caption = urlDecode(params.caption)
		if #caption > MAX_CAPTION or hasControlChars(caption) then
			fail("说明文字太长或含控制字符。")
		end
	end
	if params.add_kw ~= nil then
		addNames = splitKeywords(params.add_kw, "add_kw")
	end
	if params.remove_kw ~= nil then
		removeNames = splitKeywords(params.remove_kw, "remove_kw")
	end
	if rating == nil and flag == nil and color == nil and title == nil and caption == nil and not addNames and not removeNames then
		fail("没有要修改的内容。")
	end

	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，不支持修改。")
	end
	local before = readMetadata(photo)

	local result = catalog:withWriteAccessDo("LrMCP " .. editId, function()
		if rating ~= nil then
			photo:setRawMetadata("rating", rating > 0 and rating or nil)
		end
		if flag ~= nil then
			photo:setRawMetadata("pickStatus", flag)
		end
		if color ~= nil then
			photo:setRawMetadata("colorNameForLabel", color)
		end
		if title ~= nil then
			photo:setRawMetadata("title", title)
		end
		if caption ~= nil then
			photo:setRawMetadata("caption", caption)
		end
		for _, name in ipairs(addNames or {}) do
			local keyword = catalog:createKeyword(name, {}, true, nil, true)
			if keyword then
				photo:addKeyword(keyword)
			end
		end
		if removeNames then
			local wanted = {}
			for _, name in ipairs(removeNames) do
				wanted[name] = true
			end
			for _, keyword in ipairs(photo:getRawMetadata("keywords") or {}) do
				if wanted[keyword:getName()] then
					photo:removeKeyword(keyword)
				end
			end
		end
	end, { timeout = 15 })
	if result ~= "executed" then
		fail("Lightroom 现在不能写入（可能正忙），没有做任何修改，请稍后再试。")
	end

	local after = readMetadata(photo)
	local verified = true
	if rating ~= nil and after.rating ~= rating then verified = false end
	if flag ~= nil and after.flag ~= PICK_TO_FLAG[flag] then verified = false end
	if color ~= nil and asciiLower(after.color_label) ~= color then verified = false end
	if title ~= nil and after.title ~= title then verified = false end
	if caption ~= nil and after.caption ~= caption then verified = false end
	local nowHas = {}
	for _, name in ipairs(after.keywords) do
		nowHas[name] = true
	end
	for _, name in ipairs(addNames or {}) do
		if not nowHas[name] then verified = false end
	end
	for _, name in ipairs(removeNames or {}) do
		if nowHas[name] then verified = false end
	end
	return { before = before, after = after, verified = verified, photo = describe(photo) }
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Export (v0.13): writes a JPEG of the photo as it looks now (adjustments and crop included) into the folder the USER names
-- in the chat (parameter "folder", an absolute path, percent-encoded), or into a standard place by name (destination =
-- desktop | pictures | documents | data). Because a path now comes from a request, it is checked here and not trusted:
-- it must be an existing local folder (no network paths, no "..", nothing under system folders or this tool's own data),
-- the file name is made here from the photo's file name, the file type is always JPEG, and a file is never overwritten.
-- Not sent to the AI service.
-- ---------------------------------------------------------------------------------------------------------------------
local MAX_EXPORT_EDGE = 20000
local BLOCKED_FOLDERS = {
	"/windows/", "/program files", "/programdata/", "/appdata/", "/.ssh/", "/lrmcp/", "/system/", "/library/", "/usr/",
	"/bin/", "/sbin/", "/etc/", "/applications/", "/adobe/lightroom/modules",
}

local function checkExportFolder(path)
	if path == "" or #path > 400 or path:find(CONTROL_CHARS) then
		fail("导出文件夹的路径不合法（为空、太长或含控制字符）。")
	end
	if path:sub(1, 2) == "\\\\" or path:sub(1, 2) == "//" then
		fail("不允许导出到网络路径。请用本机的文件夹。")
	end
	if not LrPathUtils.isAbsolute(path) then
		fail("导出文件夹必须是完整路径，比如 D:\\照片\\导出 。")
	end
	local norm = asciiLower((path:gsub("\\", "/"))) .. "/"
	norm = norm:gsub("//+", "/")
	for part in norm:gmatch("[^/]+") do
		if part == ".." then
			fail("路径里不能有 .. 。")
		end
	end
	for _, bad in ipairs(BLOCKED_FOLDERS) do
		if norm:find(bad, 1, true) and not (bad == "/lrmcp/" and norm:find("/lrmcp/exports/", 1, true)) then
			fail("这个位置不允许导出（系统目录，或本工具自己的数据目录）：" .. path)
		end
	end
	if LrFileUtils.exists(path) ~= "directory" then
		fail("这个文件夹不存在，或者不是文件夹：" .. path .. "。导出不会替你创建文件夹，请先建好。")
	end
end

-- Parameters: photo=<"selected"|uuid>, and ONE of folder=<percent-encoded absolute path> | destination=desktop|pictures|documents|data;
-- optional long_edge=0 (original size) | 256..20000, quality=40..100, metadata=minimal|all,
-- format=jpeg (default) | tiff, bit_depth=8|16 (TIFF only, default 16; quality is ignored for TIFF).
-- TIFF is reachable only from the desktop app: the MCP tool lr_export never sends "format".
function M.export_photo(params)
	local catalog = LrApplication.activeCatalog()
	local photo = photoFromRef(catalog, params.photo)
	if photo:getRawMetadata("isVideo") then
		fail("这是视频文件，暂不支持导出。")
	end
	local format = params.format
	if format == nil or format == "" then
		format = "jpeg"
	end
	if format ~= "jpeg" and format ~= "tiff" then
		fail("format 只能是 jpeg 或 tiff。")
	end
	local isTiff = format == "tiff"
	local bitDepth = 16
	if isTiff and params.bit_depth ~= nil and params.bit_depth ~= "" then
		bitDepth = tonumber(params.bit_depth)
		if bitDepth ~= 8 and bitDepth ~= 16 then
			fail("bit_depth 只能是 8 或 16。")
		end
	end
	local destination = params.destination
	local root
	if params.folder and params.folder ~= "" then
		root = (params.folder:gsub("%%(%x%x)", function(h)
			return string.char(tonumber(h, 16))
		end))
		checkExportFolder(root)
		destination = "folder"
	elseif destination == "desktop" or destination == "pictures" or destination == "documents" then
		root = LrPathUtils.getStandardFilePath(destination)
	elseif destination == "data" then
		root = LrPathUtils.child(LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp"), "exports")
		LrFileUtils.createAllDirectories(root)
	else
		fail("请让用户说清楚导出到哪里：用 folder 给完整路径，或用 destination=desktop / pictures / documents。")
	end
	local longEdge = tonumber(params.long_edge) or 0
	if longEdge ~= 0 and (longEdge ~= longEdge or longEdge < 256 or longEdge > MAX_EXPORT_EDGE) then
		fail(string.format("long_edge 要么是 0（原始尺寸），要么在 256 到 %d 之间。", MAX_EXPORT_EDGE))
	end
	longEdge = math.floor(longEdge)
	local quality = tonumber(params.quality) or 90
	if quality ~= quality then
		quality = 90
	end
	quality = math.max(40, math.min(100, math.floor(quality)))
	local minimal = params.metadata ~= "all"
	local ext = isTiff and LrExportSettings.extensionForFormat("TIFF") or "jpg"

	-- the file name comes from the photo's own file name, only safe characters; the first free name is used
	local leaf = LrPathUtils.leafName(photo:getRawMetadata("path") or "photo")
	local base = (LrPathUtils.removeExtension(leaf):gsub("[^A-Za-z0-9%-_]", "_"))
	if base == "" then
		base = "photo"
	end
	local stem = base .. "_LrMCP" .. (longEdge > 0 and ("_" .. longEdge .. "px") or "_full")
	local name, n = stem, 1
	while LrFileUtils.exists(LrPathUtils.child(root, name .. "." .. ext)) do
		n = n + 1
		name = stem .. "_" .. n
	end
	local path = LrPathUtils.child(root, name .. "." .. ext)

	LrExportSession({
		photosToExport = { photo },
		exportSettings = exportSettings(name, root, longEdge, quality / 100, minimal, isTiff and { bitDepth = bitDepth } or nil),
	}):doExportOnCurrentTask()
	if not LrFileUtils.exists(path) then
		fail("Lightroom 没有生成导出文件（可能被导出设置、磁盘空间或权限拦截）。")
	end
	local attrs = LrFileUtils.fileAttributes(path)
	local dims = photo:getRawMetadata("croppedDimensions") or photo:getRawMetadata("dimensions") or {}
	local width, height = dims.width, dims.height
	if width and height and longEdge > 0 and math.max(width, height) > longEdge then
		local scale = longEdge / math.max(width, height)
		width, height = math.floor(width * scale + 0.5), math.floor(height * scale + 0.5)
	end
	return {
		path = path,
		file = name .. "." .. ext,
		folder = root,
		destination = destination,
		bytes = attrs and attrs.fileSize,
		width = width,
		height = height,
		long_edge = longEdge,
		format = format,
		extension = ext,
		quality = (not isTiff) and quality or nil,
		bit_depth = isTiff and bitDepth or nil,
		metadata = minimal and "minimal" or "all",
		photo = describe(photo),
	}
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Import (v0.15): adds ONE photo file that already sits on this computer to the catalog, the same as "Add" in Lightroom's
-- import dialog (nothing is moved, copied or deleted; no develop or metadata preset). It is for the desktop app only and is
-- NOT an MCP tool, so the AI cannot call it. Because a path comes from a request, it is checked here and not trusted:
-- a local drive path (X:\...), no network path, no "..", nothing under the system folders of BLOCKED_FOLDERS (this tool's own
-- data folder included), an existing file (not a folder) with a photo extension. Parameter: path=<percent-encoded>.
-- ---------------------------------------------------------------------------------------------------------------------
local IMPORT_EXTENSIONS = {
	jpg = true, jpeg = true, arw = true, cr2 = true, cr3 = true, nef = true, nrw = true, raf = true, orf = true,
	rw2 = true, dng = true, tif = true, tiff = true, heic = true, heif = true, png = true,
}

local function checkImportPath(path)
	if path == "" or #path > 400 or path:find(CONTROL_CHARS) then
		fail("照片路径不合法（为空、太长或含控制字符）。")
	end
	if path:sub(1, 2) == "\\\\" or path:sub(1, 2) == "//" then
		fail("不允许导入网络路径上的照片。请用本机磁盘上的文件。")
	end
	if not path:match("^[A-Za-z]:[\\/]") then
		fail("照片路径必须是本机的完整路径，比如 D:\\照片\\a.jpg 。")
	end
	local norm = asciiLower((path:gsub("\\", "/")))
	norm = norm:gsub("//+", "/")
	for part in norm:gmatch("[^/]+") do
		if part == ".." then
			fail("路径里不能有 .. 。")
		end
	end
	for _, bad in ipairs(BLOCKED_FOLDERS) do
		if (norm .. "/"):find(bad, 1, true) then
			fail("这个位置不允许导入（系统目录，或本工具自己的数据目录）：" .. path)
		end
	end
	local ext = path:match("%.([^%.\\/]+)$")
	if not ext or not IMPORT_EXTENSIONS[asciiLower(ext)] then
		fail("不支持这种文件格式（只接受常见的照片格式：jpg jpeg arw cr2 cr3 nef nrw raf orf rw2 dng tif tiff heic heif png）：" .. path)
	end
	local kind = LrFileUtils.exists(path)
	if kind == "directory" then
		fail("这是一个文件夹，不是照片文件：" .. path)
	end
	if kind ~= "file" then
		fail("这个文件不存在：" .. path .. "。导入不会替你创建或复制文件。")
	end
end

function M.import_photo(params)
	local raw = params.path
	if raw == nil or raw == "" then
		fail("请给出要导入的照片路径（path）。")
	end
	local path = (raw:gsub("%%(%x%x)", function(h)
		return string.char(tonumber(h, 16))
	end))
	checkImportPath(path)
	local catalog = LrApplication.activeCatalog()
	local name = LrPathUtils.leafName(path)
	local existing = catalog:findPhotoByPath(path)
	if existing then
		return { already = true, imported = false, id = existing:getRawMetadata("uuid"), name = name, photo = describe(existing) }
	end

	local added, addError
	local result = catalog:withWriteAccessDo("LrMCP import", function()
		-- LrTasks.pcall, not pcall: addPhoto yields inside the write gate and a plain pcall forbids that
		-- ("AgEventLoop.yieldToScheduler called when yielding is not allowed", found on real Lightroom 15.2).
		local ok, res = LrTasks.pcall(function()
			return catalog:addPhoto(path)
		end)
		if ok then
			added = res
		else
			addError = type(res) == "table" and res.lrmcp or tostring(res)
		end
	end, { timeout = 15 })
	if result ~= "executed" then
		fail("Lightroom 现在不能写入（可能正忙），没有导入任何照片，请稍后再试。")
	end
	if addError then
		fail("Lightroom 拒绝导入这个文件：" .. addError)
	end
	local photo = added or catalog:findPhotoByPath(path)
	if not photo then
		fail("Lightroom 没有报错，但在目录里没找到这张照片，请在 Lightroom 里确认。")
	end
	return { already = false, imported = true, id = photo:getRawMetadata("uuid"), name = name, photo = describe(photo) }
end

-- ---------------------------------------------------------------------------------------------------------------------
-- Library browsing for the desktop app (v0.15): list_folder_photos, get_thumbnails, select_photos. They exist so the app can show
-- the photos of a folder and let the user pick there, instead of in Lightroom. Desktop app only, NOT MCP tools (the AI cannot call
-- them). list_folder_photos and get_thumbnails only read; select_photos changes Lightroom's selection (and, if asked, the folder
-- shown), never a photo or the catalog. Paths and ids come from a request and are checked here. None of them is wrapped in the
-- write gate: nothing is written. Waiting for a thumbnail uses LrTasks.sleep (and LrTasks.pcall), never a bare pcall.
-- ---------------------------------------------------------------------------------------------------------------------
local LIST_DEFAULT, LIST_MAX = 200, 500
local THUMB_MAX_IDS, THUMB_MIN, THUMB_MAX, THUMB_DEFAULT = 24, 64, 512, 256
local THUMB_MAX_BYTES = 150 * 1024
local THUMB_TIMEOUT = 8 -- seconds per photo
local SELECT_MAX_IDS = 50

local function urlDecode(text)
	return (text:gsub("%%(%x%x)", function(h)
		return string.char(tonumber(h, 16))
	end))
end

-- a folder of the catalog: local drive path, no network path, no "..", not under BLOCKED_FOLDERS. It need not exist on disk
-- (a folder can be offline) and is not created; whether it is in the catalog is found out with getFolderByPath.
local function checkLibraryFolder(path)
	if path == "" or #path > 400 or path:find(CONTROL_CHARS) then
		fail("文件夹路径不合法（为空、太长或含控制字符）。")
	end
	if path:sub(1, 2) == "\\\\" or path:sub(1, 2) == "//" then
		fail("不允许使用网络路径。请用本机磁盘上的文件夹。")
	end
	if not path:match("^[A-Za-z]:[\\/]") then
		fail("文件夹路径必须是本机的完整路径，比如 D:\\照片 。")
	end
	local norm = asciiLower((path:gsub("\\", "/")))
	norm = norm:gsub("//+", "/")
	for part in norm:gmatch("[^/]+") do
		if part == ".." then
			fail("路径里不能有 .. 。")
		end
	end
	for _, bad in ipairs(BLOCKED_FOLDERS) do
		if (norm .. "/"):find(bad, 1, true) then
			fail("这个位置不允许浏览（系统目录，或本工具自己的数据目录）：" .. path)
		end
	end
end

local function folderPathArg(raw)
	if raw == nil or raw == "" then
		fail("请给出文件夹路径。")
	end
	local path = urlDecode(raw)
	checkLibraryFolder(path)
	if #path > 3 then
		path = path:gsub("[\\/]+$", "")
	end
	return path
end

local function parseIds(raw, maxCount, what)
	if raw == nil or raw == "" then
		fail("请给出照片 id（" .. what .. "）。")
	end
	local ids, seen = {}, {}
	for id in urlDecode(raw):gmatch("[^,]+") do
		if #id > 64 or not id:match("^[A-Za-z0-9%-]+$") then
			fail("照片 id 不合法：只能是字母、数字和连字符。")
		end
		if not seen[id] then
			seen[id] = true
			ids[#ids + 1] = id
		end
	end
	if #ids == 0 then
		fail("请给出照片 id（" .. what .. "）。")
	end
	if #ids > maxCount then
		fail(string.format("一次最多 %d 张照片。", maxCount))
	end
	return ids
end

function M.list_folder_photos(params)
	local path = folderPathArg(params.path)
	local recursive = params.recursive ~= "0"
	local offset = math.floor(tonumber(params.offset) or 0)
	local limit = math.floor(tonumber(params.limit) or LIST_DEFAULT)
	if offset ~= offset or offset < 0 then
		fail("offset 不能是负数。")
	end
	if limit ~= limit or limit < 1 or limit > LIST_MAX then
		fail(string.format("limit 要在 1 到 %d 之间。", LIST_MAX))
	end
	local catalog = LrApplication.activeCatalog()
	local folder = catalog:getFolderByPath(path)
	if not folder then
		return { in_catalog = false, total = 0, offset = offset, folder = path, photos = Json.array({}) }
	end
	local entries = {}
	for _, photo in ipairs(folder:getPhotos(recursive) or {}) do
		local p = photo:getRawMetadata("path") or ""
		entries[#entries + 1] = { photo = photo, path = p, key = asciiLower((p:gsub("\\", "/"))), uuid = photo:getRawMetadata("uuid") or "" }
	end
	table.sort(entries, function(a, b)
		if a.key ~= b.key then
			return a.key < b.key
		end
		return a.uuid < b.uuid
	end)
	local root = asciiLower((path:gsub("\\", "/"))):gsub("/+$", "")
	local out = {}
	for i = offset + 1, math.min(#entries, offset + limit) do
		local e = entries[i]
		local photo = e.photo
		local dims = photo:getRawMetadata("dimensions") or {}
		local pick = photo:getRawMetadata("pickStatus")
		local dir = (e.path:gsub("\\", "/")):match("^(.*)/[^/]*$") or ""
		local subfolder = ""
		if asciiLower(dir):sub(1, #root) == root then
			subfolder = dir:sub(#root + 2)
		end
		out[#out + 1] = {
			id = e.uuid,
			name = LrPathUtils.leafName(e.path),
			path = e.path,
			subfolder = subfolder,
			format = photo:getRawMetadata("fileFormat"),
			rating = photo:getRawMetadata("rating"),
			flag = (pick == 1 and "pick") or (pick == -1 and "reject") or "none",
			captured = photo:getRawMetadata("dateTimeOriginalISO8601"),
			width = dims.width,
			height = dims.height,
			is_virtual_copy = photo:getRawMetadata("isVirtualCopy") and true or false,
		}
	end
	return { in_catalog = true, total = #entries, offset = offset, folder = path, recursive = recursive, photos = Json.array(out) }
end

-- width and height from the JPEG's start-of-frame marker (nil when it cannot be read)
local function jpegSize(data)
	local pos, n = 3, #data
	while pos + 8 <= n do
		if data:byte(pos) ~= 0xFF then
			return nil
		end
		local m = data:byte(pos + 1)
		if m == 0xFF then
			pos = pos + 1
		elseif m == 0x01 or (m >= 0xD0 and m <= 0xD9) then
			pos = pos + 2
		else
			if m >= 0xC0 and m <= 0xCF and m ~= 0xC4 and m ~= 0xC8 and m ~= 0xCC then
				return data:byte(pos + 7) * 256 + data:byte(pos + 8), data:byte(pos + 5) * 256 + data:byte(pos + 6)
			end
			pos = pos + 2 + data:byte(pos + 2) * 256 + data:byte(pos + 3)
		end
	end
	return nil
end

-- ask for one thumbnail and wait (this task sleeps, Lightroom keeps running) at most THUMB_TIMEOUT seconds. Returns data or nil, error.
local function fetchThumbnail(photo, size)
	local done, data, err = false, nil, nil
	local ok, request = LrTasks.pcall(function()
		return photo:requestJpegThumbnail(size, size, function(d, e)
			done, data, err = true, d, e
		end)
	end)
	if not ok then
		return nil, tostring(type(request) == "table" and request.lrmcp or request)
	end
	local deadline = LrDate.currentTime() + THUMB_TIMEOUT
	while not done and LrDate.currentTime() < deadline do
		LrTasks.sleep(0.05)
	end
	local keep = request -- the request object must stay referenced until the callback has run
	if not done then
		return nil, "timeout"
	end
	if type(data) ~= "string" or data == "" then
		return nil, tostring(err or "no_data")
	end
	return data
end

function M.get_thumbnails(params)
	local ids = parseIds(params.ids, THUMB_MAX_IDS, "ids")
	local size = THUMB_DEFAULT
	if params.size ~= nil and params.size ~= "" then
		size = tonumber(params.size)
		if not size or size ~= size or size < THUMB_MIN or size > THUMB_MAX then
			fail(string.format("size 要在 %d 到 %d 之间。", THUMB_MIN, THUMB_MAX))
		end
		size = math.floor(size)
	end
	local catalog = LrApplication.activeCatalog()
	local out = {}
	for _, id in ipairs(ids) do
		local photo = catalog:findPhotoByUuid(id)
		if not photo then
			out[#out + 1] = { id = id, ok = false, error = "not_found" }
		else
			local data, err = fetchThumbnail(photo, size)
			if data and #data > THUMB_MAX_BYTES then
				data, err = fetchThumbnail(photo, math.max(THUMB_MIN, math.floor(size * 0.6)))
				if data and #data > THUMB_MAX_BYTES then
					data, err = nil, "too_large"
				end
			end
			if data then
				local w, h = jpegSize(data)
				out[#out + 1] = { id = id, ok = true, jpeg_base64 = LrStringUtils.encodeBase64(data), width = w, height = h, bytes = #data }
			else
				out[#out + 1] = { id = id, ok = false, error = err }
			end
		end
	end
	return { size = size, thumbnails = Json.array(out) }
end

local function selectedIds(catalog)
	-- getTargetPhotos() returns the whole filmstrip when nothing is selected, so look at getTargetPhoto() first
	local ids = {}
	if not catalog:getTargetPhoto() then
		return ids
	end
	for _, p in ipairs(catalog:getTargetPhotos() or {}) do
		ids[#ids + 1] = p:getRawMetadata("uuid")
	end
	return ids
end

function M.select_photos(params)
	local ids = parseIds(params.ids, SELECT_MAX_IDS, "ids")
	local activeId = params.active
	if activeId ~= nil and activeId ~= "" then
		activeId = urlDecode(activeId)
		if #activeId > 64 or not activeId:match("^[A-Za-z0-9%-]+$") then
			fail("active 不合法：只能是照片 id。")
		end
	else
		activeId = nil
	end
	local folderPath
	if params.show_folder ~= nil and params.show_folder ~= "" then
		folderPath = folderPathArg(params.show_folder)
	end
	local catalog = LrApplication.activeCatalog()
	local found, missing, byId = {}, {}, {}
	for _, id in ipairs(ids) do
		local photo = catalog:findPhotoByUuid(id)
		if photo then
			found[#found + 1] = photo
			byId[id] = photo
		else
			missing[#missing + 1] = id
		end
	end
	if #found == 0 then
		fail("在当前目录里找不到这些照片：id 无效，或 Lightroom 现在打开的是另一个目录。")
	end
	local active = activeId and byId[activeId] or found[1]
	if activeId and not byId[activeId] then
		missing[#missing + 1] = activeId
	end
	local others = {}
	for _, p in ipairs(found) do
		if p ~= active then
			others[#others + 1] = p
		end
	end

	local folderShown, folderNote = nil, nil
	if folderPath then
		local folder = catalog:getFolderByPath(folderPath)
		if not folder then
			folderShown, folderNote = false, "这个文件夹不在目录里，没有切换文件夹。"
		else
			local ok, res = LrTasks.pcall(function()
				return catalog:setActiveSources({ folder })
			end)
			folderShown = ok and res == true
			if not folderShown then
				folderNote = "Lightroom 没有切换到这个文件夹。"
			end
		end
	end

	-- Right after setActiveSources Lightroom needs a moment to show the folder; until then the photos are not in the current
	-- view and setSelectedPhotos selects nothing without an error (seen on real Lightroom 15.2): wait, select, read back, and
	-- try again a few times. Without a folder switch there is one attempt only.
	local attempts = folderShown and 5 or 1
	if folderShown then
		LrTasks.sleep(0.3)
	end
	local ok, err, selected, notSelected
	for attempt = 1, attempts do
		ok, err = LrTasks.pcall(function()
			catalog:setSelectedPhotos(active, others)
		end)
		selected = selectedIds(catalog)
		local got = {}
		for _, id in ipairs(selected) do
			got[id] = true
		end
		notSelected = {}
		for _, p in ipairs(found) do
			local id = p:getRawMetadata("uuid")
			if not got[id] then
				notSelected[#notSelected + 1] = id
			end
		end
		if not ok or #notSelected == 0 or attempt == attempts then
			break
		end
		LrTasks.sleep(0.4)
	end
	local reason
	if not ok then
		reason = "Lightroom 拒绝了选中操作：" .. tostring(type(err) == "table" and err.lrmcp or err)
	elseif #notSelected > 0 then
		reason = "有照片没有被选中：它们可能不在 Lightroom 当前显示的文件夹或集合里。可以带上 show_folder 让 Lightroom 先切到照片所在的文件夹。"
	end
	return {
		selected = Json.array(selected),
		missing = Json.array(missing),
		not_selected = Json.array(notSelected),
		all_selected = ok and #notSelected == 0,
		folder_shown = folderShown,
		reason = reason or folderNote,
	}
end

local COMMANDS = {
	status = M.status,
	list_selected = M.list_selected,
	get_develop = M.get_develop,
	get_preview = M.get_preview,
	set_develop = M.set_develop,
	list_presets = M.list_presets,
	snapshot = M.snapshot,
	apply_preset = M.apply_preset,
	restore_settings = M.restore_settings,
	export_photo = M.export_photo,
	import_photo = M.import_photo,
	list_folder_photos = M.list_folder_photos,
	get_thumbnails = M.get_thumbnails,
	select_photos = M.select_photos,
	get_metadata = M.get_metadata,
	set_metadata = M.set_metadata,
}

function M.run(command, params)
	local handler = COMMANDS[command]
	if not handler then
		fail("插件不认识这个命令：" .. tostring(command))
	end
	return handler(params or {})
end

return M
