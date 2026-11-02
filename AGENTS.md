# AGENTS.md — for AI coding agents working on this repository

(If you only want to **install or use** the software for a user, read [`AI_GUIDE.md`](AI_GUIDE.md) instead.)

## What this repo is

A Lightroom Classic plug-in (Lua, `plugin/lrmcp.lrdevplugin`) and a Python MCP server (`server/lightroom_mcp`).
The server hosts a local HTTP queue on `127.0.0.1` (first free port in 58770–58789, one server per AI session, announced in `~/LrMcp/servers/<port>.txt`); the plug-in polls all of them and runs whitelisted commands.
Version 0.11.0 reads photos and can make small, guarded changes (89 whitelisted sliders incl. RAW temperature/tint, colour grading, calibration, parametric curve, detail and effects, crop and straighten, plus catalog information (rating, flag, colour label, title, caption, keywords), a dry-run-first batch tool (at most 10 photos) and develop presets without masks (applied by Lightroom, undone by writing back every changed setting), plus 4 point curves; restorable).
Windows + Lightroom Classic 15.2 is the only tested combination.

## Commands

```powershell
cd server
python -m pytest -q                      # unit tests (no Lightroom needed)
python tests/smoke_stdio.py <cmd>        # real MCP client over stdio (set SMOKE_FULL=1 with Lightroom connected)
python tests/acceptance.py               # read tools; needs Lightroom + test catalog + the plug-in loaded + one photo selected
python tests/acceptance_write.py         # write tools; same needs; refuses unless the catalog path contains "ceshi"
python tests/lua_syntax.py               # compile every plug-in Lua file with Lua 5.1 (pip install lupa)
powershell -ExecutionPolicy Bypass -File ../build.ps1   # exe + installer (needs conda env "lrmcp", Inno Setup)
```

## Rules

1. **Never test against a real photo catalog.** Use a throw-away test catalog. Scripts and docs assume it has `ceshi`
   in its path; do not weaken that guard.
2. **Anything that writes to photos** needs: key whitelist, range checks, a per-call step limit, a backup of the old
   values, a restore path, a read-only switch, and tests. Restore = write the saved values back (snapshots and
   `LrUndo` were measured to be unreliable, see `docs/实验记录.md`).
3. **Do not commit the Adobe SDK** or text copied from Adobe's samples. No personal paths, e-mail addresses, tokens
   or photos. Commit author e-mail must stay the GitHub noreply address.
4. Shared files live in `C:\Users\<user>\LrMcp`, **never in AppData** (Claude Desktop is an MSIX app and redirects the
   AppData writes of programs it starts).
5. Messages shown to the user are Chinese; code, tool names and commit-visible docs may be English or Chinese.

## Lightroom Lua sandbox facts (measured on 15.2; see `docs/实验记录.md`)

- `os.getenv` and `os.execute` do not exist; use `LrPathUtils.getStandardFilePath("home")`; read files with `LrFileUtils`.
- Most SDK calls (`LrHttp`, `LrExportSession`, ...) must run inside `LrTasks.startAsyncTask`; develop writes must be
  inside `catalog:withWriteAccessDo` (the official docs do not say so).
- `catalog:getTargetPhotos()` returns the whole filmstrip when nothing is selected; check `getTargetPhoto()` first.
- `LrHttp` timeouts apply per phase, so the real wait is about twice the value.
- `mcp` 2.x only shows a `ToolError`'s text to the model; wrap user-facing errors (see `tools._guard`).
- On Windows `SO_REUSEADDR` lets several processes share a port; the server binds exclusively.
- The Windows console may be GBK: print through `lightroom_mcp.__main__.out`, not bare `print`, for check marks.

## Where things are

`docs/方案.md` design · `docs/实验记录.md` measured SDK behaviour · `docs/实现记录.md` implementation notes ·
`experiments/lua/` archived experiment scripts · `plugin/.../DevRun.lua` and `devscripts/` development-only bridge
(never ship them) · `installer/` + `build.ps1` release build.
