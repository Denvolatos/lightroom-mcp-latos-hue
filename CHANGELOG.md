# Changelog

Versions: a new feature raises the middle number, a small fix the last one. The server version lives in
`server/lightroom_mcp/__init__.py`, the plug-in version in `plugin/lrmcp.lrdevplugin/Version.lua` (and `Info.lua`).

## 0.1.0 — first public version (read-only)

Tested on Windows 11 with Adobe Lightroom Classic 15.2 only.

- Five read-only MCP tools: `lr_status`, `lr_list_selected`, `lr_get_develop`, `lr_get_preview`, `lr_doctor`.
- Local bridge: Python HTTP queue on `127.0.0.1:58770`, the Lightroom plug-in polls it. Random token, `Host` check,
  `Origin` refused, exclusive port (one server at a time).
- Preview: 1024 px JPEG plus histogram numbers (brightness, clipped highlights/shadows, warm/cool balance).
- `lrmcp doctor` (self check in Chinese), `lrmcp register` / `unregister` (Claude Code and Codex via their own CLIs).
- Packaging scripts: PyInstaller folder build + Inno Setup installer (`build.ps1`). **No installer is published yet**:
  installing and uninstalling it has not been tested on a clean machine.
- 30 unit tests; acceptance and smoke tests against a real Lightroom (`server/tests`).

### Not done / known issues

- Cannot change photos (planned for 0.2 / "v1.1" in the roadmap).
- Codex was not available for testing; whether it shows returned images is unverified.
- Claude Desktop is not registered automatically.
- Whether the plug-in starts on a cold Lightroom start (`LrForceInitPlugin`) is unverified.
