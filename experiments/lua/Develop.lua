-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Menu item: "LrMCP: Develop test (experiment 4)".
-- Select ONE photo in the TEST catalog first. Steps (each logged to LrMcpExp4.log):
--   read all develop settings -> export "before" preview -> snapshot -> small change
--   (Exposure2012 +0.3, Vibrance +10) -> read back -> export "after" -> restore via snapshot
--   -> change again -> restore via saved values -> undo test -> change a NON-selected photo and
--   revert -> delete our snapshot -> verify the original values are back.
-- Everything is restored at the end. Previews go to ~/LrMcp, never next to the originals.
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrExportSession = import "LrExportSession"
local LrFileUtils = import "LrFileUtils"
local LrLogger = import "LrLogger"
local LrMD5 = import "LrMD5"
local LrPathUtils = import "LrPathUtils"
local LrDate = import "LrDate"
local LrTasks = import "LrTasks"
local LrUndo = import "LrUndo"

local logger = LrLogger("LrMcpExp4")
logger:enable("logfile")

local dir = LrPathUtils.child(LrPathUtils.getStandardFilePath("home"), "LrMcp")
local DELTA_EXPOSURE, DELTA_VIBRANCE = 0.3, 10
local EPS = 1e-6

local summary = {}
local function log(text)
	logger:info(text)
end
local function say(text)
	summary[#summary + 1] = text
	logger:info("RESULT " .. text)
end
local function val(v)
	if type(v) == "number" then
		return string.format("%.4g", v)
	end
	return tostring(v)
end
local function near(a, b)
	return type(a) == "number" and type(b) == "number" and math.abs(a - b) < EPS
end
local function now()
	return LrDate.currentTime()
end

-- Run fn, log OK/FAIL with elapsed ms; return ok, result.
local function step(name, fn)
	local t0 = now()
	local ok, res = LrTasks.pcall(fn)
	local ms = (now() - t0) * 1000
	if ok then
		log(string.format("OK   %s (%.0f ms)", name, ms))
	else
		say(string.format("FAIL %s: %s", name, tostring(res)))
	end
	return ok, res
end

local function dumpSettings(s, path)
	local keys = {}
	for k in pairs(s) do
		keys[#keys + 1] = k
	end
	table.sort(keys)
	local lines = {}
	for _, k in ipairs(keys) do
		local v = s[k]
		if type(v) == "table" then
			local parts, n = {}, 0
			for _, item in ipairs(v) do
				n = n + 1
				if n <= 12 then
					parts[#parts + 1] = tostring(item)
				end
			end
			local count = 0
			for _ in pairs(v) do
				count = count + 1
			end
			lines[#lines + 1] = string.format("%s = <table entries=%d array=%d> %s", k, count, n, table.concat(parts, ","))
		else
			lines[#lines + 1] = string.format("%s = %s", k, tostring(v))
		end
	end
	local f = io.open(path, "wb")
	if f then
		f:write(table.concat(lines, "\n"), "\n")
		f:close()
	end
	return #keys
end

local function exportPreview(photo, label)
	local name = "exp4_" .. label
	local settings = {
		LR_export_destinationType = "specificFolder",
		LR_export_destinationPathPrefix = dir,
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
		LR_size_maxHeight = 1024,
		LR_size_maxWidth = 1024,
		LR_size_units = "pixels",
		LR_size_doNotEnlarge = true,
		LR_size_resolution = 72,
		LR_size_resolutionUnits = "inch",
		LR_outputSharpeningOn = false,
		LR_minimizeEmbeddedMetadata = true,
		LR_useWatermark = false,
		LR_includeVideoFiles = false,
	}
	local path = LrPathUtils.child(dir, name .. ".jpg")
	if LrFileUtils.exists(path) then
		LrFileUtils.delete(path)
	end
	local session = LrExportSession({ photosToExport = { photo }, exportSettings = settings })
	session:doExportOnCurrentTask()
	if not LrFileUtils.exists(path) then
		error("export finished but file not found: " .. path)
	end
	local attrs = LrFileUtils.fileAttributes(path)
	local data = LrFileUtils.readFile(path)
	return { path = path, size = attrs and attrs.fileSize, md5 = data and LrMD5.digest(data) }
end

local function readBack(photo, keys)
	local s = photo:getDevelopSettings()
	local out = {}
	for _, k in ipairs(keys) do
		out[k] = s[k]
	end
	return out
end

local function matches(photo, want)
	local got = readBack(photo, { "Exposure2012", "Vibrance" })
	return near(got.Exposure2012, want.Exposure2012) and near(got.Vibrance, want.Vibrance), got
end

local function findSnapshot(photo, name)
	for _, snap in ipairs(photo:getDevelopSnapshots() or {}) do
		if snap.name == name then
			return snap
		end
	end
end

LrTasks.startAsyncTask(function()
	local catalog = LrApplication.activeCatalog()
	local photo = catalog:getTargetPhoto()
	if not photo then
		LrDialogs.message("LrMCP experiment 4", "Select one photo in the test catalog first.", "info")
		return
	end

	local fmt = photo:getRawMetadata("fileFormat")
	local path = photo:getRawMetadata("path")
	local tag = tostring(fmt) .. "_" .. LrPathUtils.removeExtension(LrPathUtils.leafName(path))
	log(string.format("=== experiment 4 on %s (format=%s, virtualCopy=%s) ===", path, tostring(fmt),
		tostring(photo:getRawMetadata("isVirtualCopy"))))
	if not path:find("ceshi", 1, true) then
		LrDialogs.message("LrMCP experiment 4", "Refusing: the selected photo is not in the 'ceshi' test folder.", "info")
		return
	end

	-- 1. read all settings
	local settings
	local t0 = now()
	local ok = step("read settings", function()
		settings = photo:getDevelopSettings()
	end)
	if not ok or not settings then
		LrDialogs.message("LrMCP experiment 4", "Could not read settings; see log.", "info")
		return
	end
	local readMs = (now() - t0) * 1000
	local count = dumpSettings(settings, LrPathUtils.child(dir, "exp4_" .. tag .. "_settings.txt"))
	say(string.format("settings read: %d keys, %.0f ms (dump in ~/LrMcp/exp4_%s_settings.txt)", count, readMs, tag))
	local probe = { "Temperature", "Tint", "Texture", "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012",
		"Whites2012", "Blacks2012", "Clarity2012", "Dehaze", "Vibrance", "Saturation", "WhiteBalance",
		"ProcessVersion", "CameraProfile", "ConvertToGrayscale" }
	local present, absent = {}, {}
	for _, k in ipairs(probe) do
		if settings[k] ~= nil then
			present[#present + 1] = k .. "=" .. val(settings[k])
		else
			absent[#absent + 1] = k
		end
	end
	say("present: " .. table.concat(present, " "))
	say("ABSENT: " .. (#absent > 0 and table.concat(absent, " ") or "(none)"))

	local orig = { Exposure2012 = settings.Exposure2012, Vibrance = settings.Vibrance }
	if type(orig.Exposure2012) ~= "number" or type(orig.Vibrance) ~= "number" then
		say("STOP: Exposure2012/Vibrance are not numbers on this photo")
		LrDialogs.message("LrMCP experiment 4", table.concat(summary, "\n"), "info")
		return
	end
	local changed = { Exposure2012 = orig.Exposure2012 + DELTA_EXPOSURE, Vibrance = orig.Vibrance + DELTA_VIBRANCE }

	-- 2. export "before"
	local before
	ok, before = step("export before", function()
		return exportPreview(photo, tag .. "_before")
	end)
	if ok then
		say(string.format("export before: %s bytes md5=%s", tostring(before.size), tostring(before.md5)))
	end

	-- 3. snapshot
	local SNAP = "LrMCP-exp4"
	step("create snapshot", function()
		catalog:withWriteAccessDo("LrMCP exp4 snapshot", function()
			local made = photo:createDevelopSnapshot(SNAP, true)
			log("createDevelopSnapshot returned " .. tostring(made))
		end)
	end)
	local snap = findSnapshot(photo, SNAP)
	if snap then
		say(string.format("snapshot found: snapshotID=%s id_global=%s", tostring(snap.snapshotID), tostring(snap.id_global)))
	else
		say("snapshot NOT found after creation")
	end

	-- All writes must be inside withWriteAccessDo (confirmed in round 1: applyDevelopSettings errors otherwise).
	local function gated(actionName, fn)
		catalog:withWriteAccessDo(actionName, fn)
	end
	local function apply(target, settingsTable, historyName)
		gated(historyName, function()
			target:applyDevelopSettings(settingsTable, historyName)
		end)
	end

	-- 4. change
	step("apply change", function()
		apply(photo, changed, "LrMCP exp4 A")
	end)
	local same, got = matches(photo, changed)
	say(string.format("after change: Exposure2012=%s (want %s) Vibrance=%s (want %s) -> %s", val(got.Exposure2012),
		val(changed.Exposure2012), val(got.Vibrance), val(changed.Vibrance), same and "OK" or "MISMATCH"))

	-- 5. export "after" and compare
	local after
	ok, after = step("export after", function()
		return exportPreview(photo, tag .. "_after")
	end)
	if ok then
		say(string.format("export after: %s bytes md5=%s; differs from before: %s", tostring(after.size),
			tostring(after.md5), tostring(before and before.md5 ~= after.md5)))
	end

	-- 6. restore via snapshot (inside the write gate)
	local restoredBy
	if snap then
		for _, which in ipairs({ "snapshotID", "id_global" }) do
			local id = snap[which]
			if id and not restoredBy then
				local applied = step("apply snapshot via " .. which, function()
					gated("LrMCP exp4 snapshot restore", function()
						photo:applyDevelopSnapshot(id)
					end)
				end)
				if applied then
					local isBack = matches(photo, orig)
					log(string.format("after snapshot via %s: restored=%s", which, tostring(isBack)))
					if isBack then
						restoredBy = which
					end
				end
			end
		end
	end
	say("restore via snapshot (in write gate) worked with: " .. tostring(restoredBy))

	-- 7. change again, restore via saved values
	step("change again", function()
		apply(photo, changed, "LrMCP exp4 B")
	end)
	step("restore via saved values", function()
		apply(photo, orig, "LrMCP exp4 restore")
	end)
	local backByValues, got2 = matches(photo, orig)
	say(string.format("restore via saved values: %s (Exposure2012=%s Vibrance=%s)", backByValues and "OK" or "MISMATCH",
		val(got2.Exposure2012), val(got2.Vibrance)))

	-- 8. undo test: is one applyDevelopSettings one undo step?
	step("change for undo test", function()
		apply(photo, changed, "LrMCP exp4 C")
	end)
	local canUndo = LrUndo.canUndo()
	say("LrUndo.canUndo=" .. tostring(canUndo))
	if canUndo then
		step("LrUndo.undo", function()
			LrUndo.undo()
		end)
		LrTasks.sleep(0.5)
		local reverted, got3 = matches(photo, orig)
		say(string.format("after undo: reverted to original=%s (Exposure2012=%s Vibrance=%s)", tostring(reverted),
			val(got3.Exposure2012), val(got3.Vibrance)))
	end
	step("make sure target photo is at original", function()
		apply(photo, orig, "LrMCP exp4 restore")
	end)

	-- 9. a NON-selected photo
	local other
	for _, p in ipairs(catalog:getAllPhotos()) do
		if p.localIdentifier ~= photo.localIdentifier and tostring(p:getRawMetadata("path")):find("ceshi", 1, true) then
			other = p
			break
		end
	end
	if other then
		local o = { Exposure2012 = other:getDevelopSettings().Exposure2012 }
		if type(o.Exposure2012) == "number" then
			step("change non-selected photo", function()
				apply(other, { Exposure2012 = o.Exposure2012 + 0.1 }, "LrMCP exp4 other")
			end)
			local nowOther = other:getDevelopSettings().Exposure2012
			say(string.format("non-selected photo %s: %s -> %s (changed=%s)", LrPathUtils.leafName(other:getRawMetadata("path")),
				val(o.Exposure2012), val(nowOther), tostring(not near(nowOther, o.Exposure2012))))
			step("revert non-selected photo", function()
				apply(other, o, "LrMCP exp4 other restore")
			end)
			say("non-selected photo reverted: " .. tostring(near(other:getDevelopSettings().Exposure2012, o.Exposure2012)))
		end
	end

	-- 10. white balance: can Temperature/Tint be written? (they are absent while WhiteBalance = "As Shot")
	local wbBefore = photo:getDevelopSettings()
	say(string.format("WB before: WhiteBalance=%s Temperature=%s Tint=%s", tostring(wbBefore.WhiteBalance),
		val(wbBefore.Temperature), val(wbBefore.Tint)))
	step("apply custom white balance", function()
		apply(photo, { WhiteBalance = "Custom", Temperature = 6500, Tint = 10 }, "LrMCP exp4 WB")
	end)
	local wbAfter = photo:getDevelopSettings()
	say(string.format("WB after: WhiteBalance=%s Temperature=%s Tint=%s", tostring(wbAfter.WhiteBalance),
		val(wbAfter.Temperature), val(wbAfter.Tint)))
	local snapNow = findSnapshot(photo, SNAP)
	if snapNow then
		step("restore everything via snapshot", function()
			gated("LrMCP exp4 snapshot restore", function()
				photo:applyDevelopSnapshot(snapNow.snapshotID)
			end)
		end)
	end
	local wbRestored = photo:getDevelopSettings()
	say(string.format("WB after snapshot restore: WhiteBalance=%s Temperature=%s Tint=%s", tostring(wbRestored.WhiteBalance),
		val(wbRestored.Temperature), val(wbRestored.Tint)))

	-- 11. clean up our snapshot
	local snap2 = findSnapshot(photo, SNAP)
	if snap2 then
		step("delete our snapshot", function()
			gated("LrMCP exp4 delete snapshot", function()
				photo:deleteDevelopSnapshot(snap2.snapshotID)
			end)
		end)
		say("snapshot deleted: " .. tostring(findSnapshot(photo, SNAP) == nil))
	end

	local finalOk, finalGot = matches(photo, orig)
	local finalWb = photo:getDevelopSettings().WhiteBalance
	say(string.format("FINAL: back to original = %s (Exposure2012=%s Vibrance=%s WhiteBalance=%s, was %s)", tostring(finalOk),
		val(finalGot.Exposure2012), val(finalGot.Vibrance), tostring(finalWb), tostring(settings.WhiteBalance)))
	LrDialogs.message("LrMCP experiment 4", "Done. See LrMcpExp4.log. Final restored: " .. tostring(finalOk), "info")
end)
