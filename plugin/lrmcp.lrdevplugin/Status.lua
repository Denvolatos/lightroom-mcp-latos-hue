-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Denvolatos and contributors
-- Menu item: Library > Plug-in Extras > "LrMCP: Status". Shows which AI sessions' servers are connected.
local LrDate = import "LrDate"
local LrDialogs = import "LrDialogs"

local state = _G.LrMcp
local message
if not state then
	message = "插件还没有启动。请在 文件 → 增效工具管理器 里确认 LrMCP 已启用，必要时点“重新载入增效工具”。"
else
	local total, connected, lines = 0, 0, {}
	for port, s in pairs(state.servers or {}) do
		total = total + 1
		if s.connected then
			connected = connected + 1
			lines[#lines + 1] = string.format("  端口 %d：已连接（%.0f 秒前联系过）", port, LrDate.currentTime() - (s.lastOk or 0))
		else
			lines[#lines + 1] = string.format("  端口 %d：没连上%s", port, s.lastError and ("（" .. tostring(s.lastError) .. "）") or "")
		end
	end
	table.sort(lines)
	if total == 0 then
		message = string.format(
			"插件版本 %s。\n现在没有发现任何 Lightroom MCP 服务。\n请确认 Claude 或 Codex 已打开，并且已经登记了 lightroom_mcp。",
			state.version)
	else
		message = string.format("插件版本 %s。\n发现 %d 个 Lightroom MCP 服务（每个 AI 会话一个），%d 个已连接：\n%s",
			state.version, total, connected, table.concat(lines, "\n"))
	end
end
LrDialogs.message("LrMCP", message, "info")
