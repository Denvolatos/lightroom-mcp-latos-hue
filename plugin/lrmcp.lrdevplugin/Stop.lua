-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Called when the plug-in is disabled or unloaded: ask the bridge loop to end.
if _G.LrMcp then
	_G.LrMcp.stop = true
end
