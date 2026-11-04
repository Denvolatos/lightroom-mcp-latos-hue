-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Dev script: smoke test of the dev bridge. Read-only.
local ctx = ...
local import = ctx.import
local LrApplication = import "LrApplication"

local v = LrApplication.versionTable()
local catalog = LrApplication.activeCatalog()
return string.format("hello from Lightroom %d.%d.%d (job %s); catalog=%s; photos=%d", v.major, v.minor, v.revision,
	tostring(ctx.jobId), tostring(catalog:getPath()), #catalog:getAllPhotos())
