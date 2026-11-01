-- Menu item: Library > Plug-in Extras > "LrMCP: Status". Shows whether the Python server is connected.
local LrDate = import "LrDate"
local LrDialogs = import "LrDialogs"

local state = _G.LrMcp
local message
if not state then
	message = "插件还没有启动。请在 文件 → 增效工具管理器 里确认 LrMCP 已启用，必要时点“重新载入增效工具”。"
elseif state.connected then
	message = string.format("已连接到 Lightroom MCP 服务。\n插件版本 %s，%.0f 秒前联系过。", state.version, LrDate.currentTime() - (state.lastOk or 0))
else
	message = string.format(
		"没有连上 Lightroom MCP 服务。\n插件版本 %s。\n请确认 Claude 或 Codex 已打开，并且已经登记了 lightroom_mcp。%s",
		state.version,
		state.lastError and ("\n（最近一次错误：" .. tostring(state.lastError) .. "）") or ""
	)
end
LrDialogs.message("LrMCP", message, "info")
