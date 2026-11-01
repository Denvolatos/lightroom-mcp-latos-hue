-- Dev script: does pcall(require, "<missing file>") fail cleanly inside Lightroom? (The release build has no
-- DevRun.lua, and Bridge.lua loads it with pcall(require, ...).) Changes nothing.
local ok, err = pcall(require, "ThisFileDoesNotExist.lua")
return string.format("pcall(require, missing) -> ok=%s, plug-in still running: yes; message=%s", tostring(ok), tostring(err):sub(1, 120))
