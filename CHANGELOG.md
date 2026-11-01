# Changelog

Versions: a new feature raises the middle number, a small fix the last one. The server version lives in
`server/lightroom_mcp/__init__.py`, the plug-in version in `plugin/lrmcp.lrdevplugin/Version.lua` (and `Info.lua`).

## 0.3.0 — several AI sessions at once

- Every server takes the first free port in 58770–58789 and announces itself in `~/LrMcp/servers/<port>.txt`; the
  plug-in polls all of them. Commands from different sessions run one at a time inside Lightroom.
- `lr_status` shows the server's port and how many other sessions are connected; `lr_doctor` checks the Lightroom version.
- Preview file names are unique per call, so two sessions previewing at once never share a file.
- Acceptance run against a real Lightroom test catalog: two servers, 20 concurrent calls, simultaneous writes to one
  photo, one server stopping and another starting.
- A 0.2.x server keeps working with the 0.3 plug-in (legacy token file).

## 0.2.0 — guarded changes

- New tools: `lr_set_develop`, `lr_restore`, `lr_restore_original`, `lr_list_edits`.
- Changeable: 35 sliders (exposure, contrast, highlights, shadows, whites, blacks, texture, clarity, dehaze, vibrance,
  saturation, 24 HSL values). Range limits, a step limit per call, one photo at a time, `LrMCP <id>` history steps.
- The old values are saved before anything is written; restore writes them back. Lightroom snapshots and undo were
  measured to be unreliable, so they are not used.
- Read-only switch: file `C:\Users\<you>\LrMcp\readonly` (or `LRMCP_READONLY=1`); server and plug-in both refuse.
- Measured: Lightroom does not check slider ranges (out-of-range values are stored as given), so this project does.
- The token file is written back if something deletes it while the server runs.
- 74 tests (Python logic, the plug-in's Lua write logic against a fake SDK, a whitelist consistency check) and a write
  acceptance run against a real Lightroom test catalog (20 checks: refused changes change nothing, everything restores
  to the start, the preview is pixel-identical).
- Not included: white balance (RAW values only appear after an edit; needs more measuring), tone curve, masks, crop.

## 0.4.0 — update notice, Chinese-first docs

- `AI_GUIDE.md` (install and usage procedure written for AI assistants), `llms.txt`, `AGENTS.md` (for AI coding agents).
- Update notice: once a day the server checks GitHub for a newer release and `lr_status` mentions it (no automatic
  download). Opt out with `LRMCP_NO_UPDATE_CHECK=1` or the file `~/LrMcp/no_update_check`; see SECURITY.md.
- The default README is now Chinese (`README.md`); the English one is `README.en.md`. SECURITY.md has a Chinese part first.
- Feedback channel: GitHub issue forms (bug report, compatibility report, feature request) and Discussions.

## 0.1.0 — first public version (read-only)

Tested on Windows 11 with Adobe Lightroom Classic 15.2 only.

- Five read-only MCP tools: `lr_status`, `lr_list_selected`, `lr_get_develop`, `lr_get_preview`, `lr_doctor`.
- Local bridge: Python HTTP queue on `127.0.0.1:58770`, the Lightroom plug-in polls it. Random token, `Host` check,
  `Origin` refused, exclusive port per server.
- Preview: 1024 px JPEG plus histogram numbers (brightness, clipped highlights/shadows, warm/cool balance).
- `lrmcp doctor` (self check in Chinese), `lrmcp register` / `unregister` (Claude Code and Codex via their own CLIs).
- Packaging scripts: PyInstaller folder build + Inno Setup installer (`build.ps1`). **No installer is published yet**:
  installing and uninstalling it has not been tested on a clean machine.
- 30 unit tests; acceptance and smoke tests against a real Lightroom (`server/tests`).

### Not done / known issues

- (0.1.0) Could not change photos; 0.2.0 adds guarded changes.
- Codex was not available for testing; whether it shows returned images is unverified.
- Claude Desktop is not registered automatically.
- Whether the plug-in starts on a cold Lightroom start (`LrForceInitPlugin`) is unverified.
