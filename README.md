# 📸 Lightroom MCP for Windows

**Let Claude or Codex look at your photos in Adobe Lightroom Classic.**
A Lightroom plug-in plus a small MCP server. It can see the photo you selected, read its develop settings, and show
the assistant a preview with histogram numbers. **Read-only for now: it cannot change your photos.**

![License: MIT](https://img.shields.io/badge/license-MIT-blue) ![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey) ![Status: early](https://img.shields.io/badge/status-early%200.1.0-orange)

[中文说明](README.zh-CN.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

> ⚠️ **Early version (0.1.0).** Tested only on Windows 11 with Lightroom Classic 15.2. No installer is published yet.
> Not affiliated with Adobe.

## ✨ What it does

| Tool | What it gives the assistant |
|---|---|
| `lr_status` | Is Lightroom connected, its version, the open catalog, how many photos are selected |
| `lr_list_selected` | Selected photos: name, format, rating, size, ISO / aperture / shutter / focal length / lens / camera |
| `lr_get_develop` | Current develop settings: exposure, contrast, highlights, shadows, white balance, HSL, … |
| `lr_get_preview` | A 1024 px preview (256–2048) **plus numbers**: brightness, clipped highlights/shadows, warm/cool balance |
| `lr_doctor` | Self check in Chinese: what is wrong and how to fix it |

Example: select a photo and ask *"Look at the selected photo and tell me what is wrong with the exposure."*
The assistant gets the picture and numbers such as `mean brightness 77.6`, `warm/cool index −9.9 %` and can say
*"a bit dark and cool"* with evidence.

It never writes to your photos: the only files it creates are preview JPEGs, a token and a log in
`C:\Users\<you>\LrMcp` (previews are not added to your catalog).

## 🏗️ How it works

```
Claude / Codex ──(MCP, stdio)──▶ lrmcp (Python server, local queue on 127.0.0.1:58770)
                                          ▲
              Lightroom plug-in (Lua) polls the queue, runs a whitelisted command, sends the answer back
```

- Local only: the server binds `127.0.0.1` exclusively, requests need a random token, the `Host` header must match,
  and requests with an `Origin` header (browsers) are refused. One server instance at a time.
- The plug-in runs a fixed whitelist of commands and never takes a file path from a request.
- Note: the images and photo information the tools return go to the AI service you use. See [SECURITY.md](SECURITY.md).

## 🧰 Requirements

- Windows, Adobe Lightroom Classic (developed on 15.2; SDK 15.x), Python 3.10+ (tested with 3.12).
- Claude Code, Codex, or another MCP client (Claude Code was tested; Codex was not).

## 🚀 Install from source

1. **Server** (normal PowerShell):
   ```powershell
   pip install ./server
   lrmcp register --dry-run   # shows what it would do
   lrmcp register             # registers "lightroom_mcp" with Claude Code and/or Codex (uses their own CLIs)
   ```
2. **Plug-in**: copy `plugin/lrmcp.lrdevplugin` to `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`, delete
   `DevRun.lua` and the `devscripts` folder from the copy (they are development helpers), and restart Lightroom.
   In *File → Plug-in Manager* LrMCP should be enabled. `powershell -ExecutionPolicy Bypass -File build.ps1`
   builds a clean staged copy plus an installer (needs the conda env and Inno Setup, see [CONTRIBUTING](CONTRIBUTING.md)).
3. Restart your assistant, then ask it to call `lr_status`. If something fails, ask for `lr_doctor`.

> **Windows gotcha:** *Claude Desktop is an MSIX app*, and Windows silently redirects what programs it starts write to
> `AppData`. Run installers and copy steps from your own PowerShell, not from a shell started by Claude Desktop.
> That is also why this project keeps its shared files in `C:\Users\<you>\LrMcp`, not in `AppData`.

Claude Desktop is not registered automatically (its config file location depends on how it was installed); add the
command by hand under *Settings → Developer → Edit Config*.

## 🗺️ Roadmap

| Version | Plan |
|---|---|
| 0.1 (now) | Read-only: look at photos, develop settings, preview, histogram numbers, self check |
| next | Change one photo's global sliders, with range limits, a backup of the old values and a restore command, plus a read-only switch |
| later | Teaching mode (plain-language explanations, before/after), learning your taste from rated photos, batch / presets / culling help |

Masks, AI features and tone curves depend on what Adobe's SDK offers and are not promised.

## 📚 Docs

Design notes are in Chinese for now: [`docs/方案.md`](docs/方案.md) (plan), [`docs/实验记录.md`](docs/实验记录.md) (what was
measured on Lightroom Classic 15.2: e.g. writes need `withWriteAccessDo`, snapshots and undo are unreliable),
[`docs/实现记录.md`](docs/实现记录.md) (implementation notes).

## 🙏 See also

Other Lightroom Classic MCP projects, studied for ideas (no code was copied):
[Automaat/lightroom-mcp](https://github.com/Automaat/lightroom-mcp) (TypeScript, MIT, many tools, Windows and macOS)
and [noopz/lightroom_mcp](https://github.com/noopz/lightroom_mcp) (Python, Apache-2.0).
This project aims to be small, read-only first, Python-based and easy to install for non-programmers.

## ⚖️ License and disclaimer

[MIT](LICENSE). Third-party packages: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Adobe and Lightroom are trademarks of Adobe Inc.; this project is not affiliated with, endorsed or sponsored by Adobe.
The Adobe Lightroom Classic SDK is not included and must not be committed.
