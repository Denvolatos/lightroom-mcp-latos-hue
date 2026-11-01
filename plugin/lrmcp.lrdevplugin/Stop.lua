-- Called when the plug-in is disabled or unloaded: ask the bridge loop to end.
if _G.LrMcp then
	_G.LrMcp.stop = true
end
