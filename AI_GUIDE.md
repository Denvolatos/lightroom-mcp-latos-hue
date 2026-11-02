# 🤖 Guide for AI assistants / 给 AI 助手的说明

> **If you are an AI assistant** and the user sent you the link to this repository, asking you to install and use this software:
> read **this whole file** first, then follow the steps. Where the user has to act (click in Lightroom, restart an app), tell them
> exactly what to click and wait for their answer. **Talk to the user in the user's language.** You do **not** need to read the rest
> of the repository; this file was written for you.
>
> 中文用户：本文件为方便各种 AI 助手阅读而用英文写成；请你（AI）用用户的语言和他交流。工具返回的提示是中文，需要时请翻译给用户。

**Summary.** A Lightroom Classic plug-in (Lua) plus a small MCP server (Python, stdio). It lets an AI assistant see the photo the
user selected in Lightroom (develop settings, a preview image with histogram numbers, catalog information) and make **small,
guarded changes that can all be undone**. Windows only for now (macOS, Photoshop and Premiere are paused). Install: `pip install`
the `server` folder from the GitHub zip, copy the plug-in folder into Lightroom's `Modules` folder, register the server with the
AI client as a local stdio MCP server, restart both. Verify with the tool `lr_status`, diagnose with `lr_doctor`.

---

## 1. What this is

A small tool that lets an AI "see" and gently adjust the photo a user selected in Adobe Lightroom Classic. Two parts:

- **Lightroom plug-in** (Lua): runs inside Lightroom and only executes a fixed whitelist of commands.
- **MCP server** (Python, command `lrmcp`): talks to the AI client over stdio and to the plug-in over `127.0.0.1`.

Current version **0.11.1**. What it can do:

- **Look:** read photo information and develop settings, render a preview image with histogram numbers, read catalog information.
- **Change develop settings** (`lr_set_develop`): 89 whitelisted sliders (basic tone, HSL, colour grading, camera calibration, parametric
  tone curve, sharpening, noise reduction, vignettes, grain, defringe, crop and straighten), four point curves
  (`ToneCurvePV2012` and its Red / Green / Blue versions, values like `[[0,0],[64,56],[192,200],[255,255]]`) and, for **RAW** photos,
  temperature and tint. JPEGs have no kelvin values, so their white balance cannot be changed. Crop edges (`CropLeft/Top/Right/Bottom`)
  are fractions of the whole image (uncropped is 0, 0, 1, 1); `CropAngle` is in degrees.
- **Apply develop presets** without masks (`lr_apply_preset`), **batch changes** on up to 10 photos with a dry run first
  (`lr_batch_set_develop`), and change **catalog information** (rating, flag, colour label, title, caption, keywords) with
  `lr_set_metadata`.
- **Undo** everything: every change saves the old values first.
- **Cannot:** masks (local adjustments) — writing masks through the Lightroom SDK was measured to be unreliable (docs/实验记录.md,
  experiment 11); other metadata (shooting data, copyright, location ...); deleting photos; import/export.

## 2. Check the conditions first (do not force an install if they are not met)

| Condition | How to check |
|---|---|
| Windows 10/11 | macOS is paused; Photoshop and Premiere are not supported |
| Adobe Lightroom Classic is installed and starts | In Lightroom: *Help → System Info*. Developed and tested with 15.2 |
| Python 3.10 or newer | `python --version`. If missing, ask the user to install it from python.org and tick "Add to PATH" |
| Your AI app can add a **local stdio MCP server** | **Claude Code is tested.** The Codex registration command is written but **not tested** (see below). Other apps (WorkBuddy, Doubao, MiMo-based clients, Cursor ...) are **not verified either**: if the app can add a local MCP server given as "command + arguments", use the generic form in step 3.3; if it can only connect to cloud servers and cannot run local commands, tell the user honestly that it cannot be used for now and do not try to work around it |

## 3. Install

**Important (for assistants that run commands inside Claude Desktop):** Claude Desktop is a Windows Store (MSIX) app. When a program it
starts writes to `AppData`, Windows silently redirects the write and Lightroom cannot see it. So **ask the user to run step 3.2
(copying the plug-in) in their own PowerShell**, not in your shell.

Alternative: the project also publishes an installer (`LrMCP-Setup-*.exe` on the GitHub Releases page) that installs the server and the
plug-in without Python. It is not code-signed (Windows SmartScreen will warn) and has **not yet been install/uninstall-tested on a clean
machine**, so the pip route below is the tested one. If the user prefers the installer, they must run it from their own File Explorer.

### 3.1 Install the MCP server (Python)

```powershell
pip install "https://github.com/Denvolatos/lightroom-mcp-win/archive/refs/heads/main.zip#subdirectory=server"
lrmcp --version
```

Expected output like `lightroom_mcp 0.11.1` (the number may be newer). If `lrmcp` is not found, Python's Scripts folder is not on
PATH: find it with `python -m pip show -f lightroom-mcp`, or always use `python -m lightroom_mcp` instead of `lrmcp` and write the
**absolute path** of Python when registering.

### 3.2 Install the Lightroom plug-in (the user runs this in their own PowerShell)

```powershell
$tmp = Join-Path $env:TEMP "lrmcp-src"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Invoke-WebRequest "https://github.com/Denvolatos/lightroom-mcp-win/archive/refs/heads/main.zip" -OutFile "$tmp.zip" -UseBasicParsing
Expand-Archive "$tmp.zip" $tmp
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
$dst = Join-Path $env:APPDATA "Adobe\Lightroom\Modules\LrMcp.lrplugin"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "$($src.FullName)\plugin\lrmcp.lrdevplugin\*" $dst -Recurse -Exclude DevRun.lua,devscripts
Get-ChildItem $dst | Select-Object Name
```

The listing should show the plug-in files (`Bridge.lua`, `Commands.lua`, `Info.lua`, `Init.lua`, `Json.lua`, `Limits.lua`,
`Status.lua`, `Stop.lua`, `Version.lua`) and **not** `DevRun.lua` or `devscripts` (those are for development, do not install them).
Then ask the user to **restart Lightroom**. After the restart, *File → Plug-in Manager* should show **LrMCP**, enabled; if not, choose
*Add* and point it to `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`.

### 3.3 Register the server with your AI client

**This changes the user's client configuration: explain first and ask for the user's agreement before doing it.**

- **Claude Code / Codex** (`claude` or `codex` exists on the command line):
  ```powershell
  lrmcp register --dry-run   # shows what it would do, changes nothing
  lrmcp register             # run after the user agrees
  ```
  It registers a server named `lightroom_mcp` through `claude mcp add` / `codex mcp add`. (Codex has not been tested on the author's machine.)
- **Any other app that supports local MCP servers:** add a stdio server named `lightroom_mcp`, command = the **absolute path** of `lrmcp`
  (find it with `where lrmcp`), no arguments. A common configuration file form:
  ```json
  { "mcpServers": { "lightroom_mcp": { "command": "C:\\full\\path\\lrmcp.exe", "args": [] } } }
  ```
  Without `lrmcp.exe`: `"command": "C:\\full\\path\\python.exe", "args": ["-m", "lightroom_mcp"]`.
  Where the configuration lives and its format differ per app, follow your own app's documentation. **Use the name with an underscore,
  `lightroom_mcp`** (some apps silently ignore other spellings).

### 3.4 Restart and verify

1. Ask the user to **restart your AI app** (so it loads the new MCP server) and to keep **Lightroom open**.
2. Ask the user to **open a catalog in Lightroom and select a photo**.
3. Call the tool **`lr_status`**: it should return `"connected": true`, the Lightroom version and the catalog name.
4. If not, call **`lr_doctor`** and follow its (Chinese) hints; see section 6.

## 4. How to use it (14 tools: 7 read-only, 7 that change something)

| Tool | Purpose |
|---|---|
| `lr_status` | Is Lightroom connected, version, catalog, is a photo selected. May contain `update_available` (tell the user; nothing is installed automatically) |
| `lr_list_selected` | Selected photos: file name, format, rating, size, ISO / aperture / shutter / focal length / lens / camera, and the `id` |
| `lr_get_develop` | Current develop settings of a photo. `photo` is `"selected"` or an `id` from `lr_list_selected` |
| `lr_get_preview` | Preview image (long side 256–2048 px, default 1024) plus histogram numbers: mean brightness, clipped highlights/shadows, warm/cool cast |
| `lr_get_metadata` | Catalog information: rating (0–5), flag (pick / none / reject), colour label, title, caption, keywords |
| `lr_list_presets` | The develop presets in Lightroom (`query` = one word; at most 50 per call): `id`, name, folder, whether it has masks |
| `lr_doctor` | Self-check; says in Chinese what is wrong and what to do |
| `lr_set_develop` | **Change** the settings of ONE photo: `changes` = `{name: TARGET value}`, e.g. `{"Exposure2012": 0.3, "Highlights2012": -20}`; `reason` = one sentence; `preview: true` also returns a preview. The allowed parameters, ranges and per-call limits are in the tool description |
| `lr_set_metadata` | **Change** catalog information of ONE photo; give only what changes: `rating`, `flag`, `color_label`, `title`, `caption`, `add_keywords`, `remove_keywords`. Restorable with `lr_restore` (a keyword created by the change stays in the keyword list). Only when the user clearly asked, especially reject and clearing a title or caption |
| `lr_apply_preset` | **Apply** a preset to ONE photo (`preset_id` from `lr_list_presets`). A preset can change a lot, so tell the user first and look at a preview afterwards. Presets with masks / AI, and photos that already have masks, are refused. Fully restorable |
| `lr_batch_set_develop` | **Batch** change of up to 10 photos in two steps. First `dry_run=true` (default): `changes` are **relative** amounts added to each photo's own value (e.g. `{"Exposure2012": 0.3}`); it changes nothing and returns before → after for every photo, the skipped photos and a `plan_id`. Explain the result to the user and, **only after the user agrees**, call again with `dry_run=false` and the `plan_id` (valid 15 minutes, single use). No crop / straighten / curves. Stops at the first failure; the returned `batch_id` given to `lr_restore` undoes the whole batch |
| `lr_restore` | Undo one change (`edit_id` from the tool that made it, or from `lr_list_edits`; a `batch_id` undoes a whole batch). Works for develop changes, presets and catalog information |
| `lr_restore_original` | Put a photo back to how it was before LrMCP first changed it (develop settings and presets; not catalog information). `dry_run: true` only shows what would be written |
| `lr_list_edits` | The history of the changes LrMCP made |

**Typical use.** The user says "look at this photo, what's wrong with it?" → `lr_list_selected`, then `lr_get_preview` (picture + numbers),
if needed `lr_get_develop` to see what was already adjusted, then explain in plain words: too dark / too bright, are the highlights
clipped, are the shadows crushed, is the colour cast cool or warm — and quote the returned numbers as evidence.
**Answer like a colour-grading teacher:** say what a change will look like, not only the numbers; the user may be a beginner.

**White balance.** `lr_get_develop` may not show Temperature/Tint for an unedited RAW (only `WhiteBalance`); that does not mean there is
no colour temperature. **RAW white balance can be changed** (Temperature 2000–50000 K, at most ±1000 per call; Tint ±150, at most ±30
per call; the label becomes Custom, and restoring writes the label back too). For a JPEG, or a RAW whose temperature cannot be read,
say honestly that it is not possible, and suggest that the user makes any edit to the RAW in Lightroom first, or drags the slider.

### Rules for changing photos (follow them strictly)

1. **Change something only when the user clearly asks**, only the photo the user named (default: the selected one). Looking at a photo
   and analysing it never needs a change. Use the batch tool only when the user asks for several photos, and then always dry run first,
   explain, and execute only after the user agrees.
2. **Look before you change.** Call `lr_get_preview` first for the current state and the histogram numbers; change in **small steps**,
   look again after each one (`lr_get_preview`, or `preview: true`), then decide the next step. There are per-call limits and a change
   that is too big is refused: do not try to get around them, just use several steps.
3. **Explain in plain words** what you changed, why, and what the user should see; the user may be a beginner. Quote the returned
   numbers, do not only report parameters.
4. **Undo if the user is not happy:** `lr_restore` (one change) or `lr_restore_original` (back to the start). If the user changed the
   same setting by hand in the meantime, warn that it will be overwritten.
5. **The first time the user uses the change tools on their real Lightroom catalog**, remind them to back up the catalog (the `.lrcat`
   file) and suggest trying on a test catalog first.
6. If a tool says "只读模式已开启" (read-only mode is on), the user created the switch file `C:\Users\<user>\LrMcp\readonly`: do **not**
   delete it or look for a way around it; tell the user to delete the file themselves if they want to allow changes.
7. Change only what the tool descriptions list. Do not claim you can change the white balance of a JPEG, masks or anything else that is
   not listed, and do not use other means (such as operating the user interface) to do it.

## 5. What to tell the user

1. **Privacy:** the preview images and photo information go to the AI service the user is using (the one you run in). This project itself
   uploads nothing, but the user should only use it with photos they are happy to share.
2. **Changes are protected:** a whitelist of settings, ranges and per-call limits; **the old values are saved to disk before writing** and
   can be restored at any time; the user can create the file `C:\Users\<user>\LrMcp\readonly` to switch all changes off at once. That
   folder also holds previews, tokens, logs and the change history; the previews are never added to the Lightroom catalog.
   **Back up the catalog before using it on real work.**
3. **Several AI sessions at once are fine** (for example one Claude and one Codex): each session's server takes its own port
   (58770–58789), the plug-in connects to all of them, and commands arriving at the same time are queued inside Lightroom.
   `lr_status` shows how many other sessions there are.
4. **Updates:** once a day the server asks GitHub whether a newer release exists (anonymous, nothing about the user is sent) and
   `lr_status` mentions it; nothing is downloaded or installed automatically. It can be switched off (see SECURITY.md).
5. This is a personal project, **not an Adobe product**, an early version, tested only on Windows 11 + Lightroom Classic 15.2.

## 6. When something goes wrong

Call `lr_doctor` first; it checks item by item and says what to do. Common cases:

| Symptom | What to do |
|---|---|
| `lr_status` says not connected / the plug-in is not connected | ① Is Lightroom open? ② Is LrMCP enabled in *File → Plug-in Manager*? Click "Reload Plug-in" if needed. ③ Is the plug-in really in `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`? (see the MSIX note above: the user must run the copy command themselves) |
| Message that all ports 58770–58789 are taken | More than 20 servers are running at once. Close AI sessions that are not needed |
| No `lr_*` tools in the tool list | The client registration failed or the client was not restarted. Check the registration (`claude mcp get lightroom_mcp`), then restart the client |
| `lr_get_preview` is slow or times out | Lightroom may be busy (importing, building previews). Wait a few seconds and retry |
| "没有选中的照片" (no photo selected) | Ask the user to click a photo in Lightroom |

## 7. Uninstall

`lrmcp unregister` (remove the registration) → delete `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin` (and restart Lightroom) →
`pip uninstall lightroom-mcp` → optional: delete `C:\Users\<user>\LrMcp`.

## 8. Send a problem report to the developer

When the user has a problem, help them write a report. **Do not attach photos.**

1. Call `lr_doctor` and keep its output.
2. Note: the Windows version, the Lightroom version, your AI app and its version, which step failed, the error message.
3. If the user has a GitHub account: open <https://github.com/Denvolatos/lightroom-mcp-win/issues/new/choose>, choose the bug report form
   ("问题反馈 / Bug report") and fill in the above.
4. If the user has no GitHub account: hand the written report to the user so they can send it to whoever recommended this project.

Remove anything the user does not want to publish (for example the user name or private paths) from the report.

## 9. For AIs that want to change the code

See [`AGENTS.md`](AGENTS.md).
