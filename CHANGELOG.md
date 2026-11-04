# Changelog

Versions: a new feature raises the middle number, a small fix the last one. The server version lives in
`server/lightroom_mcp/__init__.py`, the plug-in version in `plugin/lrmcp.lrdevplugin/Version.lua` (and `Info.lua`).

## 1.0.2 (2026-11-04) — version sync with Latos Hue 1.0.2

- Version number only: the plug-in and the MCP server move to **1.0.2** to match Latos Hue 1.0.2 (which fixes an installer "access denied" problem caused by Lightroom being started with the app's own folder; see `app/CHANGELOG.md`). The tools and how to use them are unchanged. After upgrading, reload the plug-in once in Lightroom (File > Plug-in Manager > Reload Plug-in). If you installed Latos Hue 1.0.0 / 1.0.1 with auto-start of Lightroom, close Latos Hue and Lightroom before upgrading.

## 1.0.1 (2026-11-04) — unified version number

- **One product, one version number.** The plug-in and MCP server (LrMCP) now share the version number of the desktop app Latos Hue: this release moves LrMCP from 0.15.0 to **1.0.1**. From now on every release carries both installers (`LatosHue-Setup-1.0.1.exe` and `LrMCP-Setup-v1.0.1.exe`) under one tag (`v1.0.1`). Nothing else changed in the plug-in or the server; the tools and how to use them are the same as in 0.15.0. After upgrading, reload the plug-in once in Lightroom (File > Plug-in Manager > Reload Plug-in).
- The GitHub repository is renamed to `lightroom-mcp-latos-hue`. The update check of Latos Hue accepts release links under both the new and the old name. The server's own update check still points at the old address (GitHub redirects it); it will be changed in the next release.

## 0.15.0 (2026-11-04) — import command and library commands for the desktop app, AGPL-3.0

- **License change:** The project's own code is now licensed under the **GNU AGPL-3.0** (was MIT), from the commits of 2026-11-03 on. In short: free
  to use, change and share; a distributed (or network-served) modified version must publish its source under the AGPL-3.0 too.
  The releases v0.1.0 to v0.14.0 that were published before stay under the MIT license.
  Every own source file now carries an `SPDX-License-Identifier: AGPL-3.0-only` header; `THIRD_PARTY_NOTICES.md` lists the bundled packages.
- New plug-in command `import_photo`: adds one photo file that is already on this computer to the Lightroom catalog, the same as
  "Add" (not move) in the import dialog. It is for the desktop app on this computer only and is **not an MCP tool**: the tool list
  is unchanged (22 tools), so an AI assistant cannot call it.
- The plug-in does not trust the path it is given. It refuses: anything that is not a local drive path (`X:\...`), network paths
  (`\\server\share\...`), `..` in the path, system and program folders and this tool's own data folder (the same list as export),
  files that do not exist or are folders, and any extension outside `jpg jpeg arw cr2 cr3 nef nrw raf orf rw2 dng tif tiff heic
  heif png` (case does not matter). A photo that is already in the catalog is not added twice (the reply says `already`).
- Nothing is moved, copied or deleted, and no develop or metadata preset is applied. The server side
  (`EditService.import_photo`) is refused by the read-only switch; a timeout is reported as "uncertain, check in Lightroom".
- TIFF export for the desktop app only: the plug-in command `export_photo` takes an optional `format` (`jpeg`, the default and
  unchanged, or `tiff`) and `bit_depth` (`8` or `16`, default 16). TIFF is sRGB with lossless ZIP compression, the file ends in
  `.tif`, `quality` does not apply, and every folder check and the never-overwrite rule are the same as for JPEG. Any other
  `format` is refused. The server side is `EditService.export_photo_for_app`, which is **not an MCP tool**: `lr_export` keeps its
  parameters and stays JPEG-only, so an AI assistant cannot ask for TIFF (the tool list is still 22 tools).
- After updating, reload the plug-in once in Lightroom (the new command lives in the plug-in).
- Also in 0.15.0 (desktop app only, **not an MCP tool**, tool list unchanged): `EditService.apply_settings` writes a set of whitelisted settings (sliders, curves, white balance label) to one photo as one change that `lr_restore` can undo. It is used by the desktop app's "my presets" after the user clicks a confirmation list; keys outside the whitelist and out-of-range numbers are refused, the read-only switch applies, and no existing tool changed. Tests added in `server/tests/test_edits.py`.
- Library browsing for the desktop app, so photos can be browsed and picked in the app instead of in Lightroom. Three new
  plug-in commands, all **desktop app only and not MCP tools** (the tool list is still 22 tools; an AI assistant cannot call
  them): `list_folder_photos` (photos of a catalog folder, with paging and an optional recursive flag; a folder that is not in
  the catalog gives an empty answer, not an error), `get_thumbnails` (up to 24 JPEG thumbnails, 64-512 px, at most 150 KB each,
  8 seconds per photo before `timeout`), and `select_photos` (selects photos in Lightroom, optionally switching to a folder
  first, and reports what is really selected afterwards). They read catalog metadata and thumbnails or change only the
  selection, never a photo or the catalog. Folder paths are checked like import and export. The server side is
  `LibraryService` in `library.py`; the read-only switch does not block it.
- Upgrading needs a plug-in reload (the three commands live in the plug-in).

## 0.14.0 — reconnect fix

- Root cause: when a server stopped and a new one took the same port straight away, the plug-in's old poller still held the
  old token. It had to wait for the old long poll (up to 10 s) to run out, then take a 401 and sleep 2 s before it re-read
  the announcement, so the new server was found only 8-11 s later. The server waits just 6 s for the plug-in, so the first
  call failed with "plug-in not connected" until Lightroom's plug-in was reloaded.
- Plug-in: the poller re-reads the port's announcement before every request and right after every failure (401/403, refused
  connection, timeout). A new token or pid is used at once and resets the failure count and back-off; a missing file ends the
  poller as before. The token is never logged.
- Server: `Bridge.stop()` removes the announcement first, then wakes every waiting `/poll` (answer "none") so the old long
  poll returns immediately, then closes the socket. `POLL_HOLD_SECONDS` is unchanged.
- After updating, reload the plug-in once (File > Plug-in Manager > Reload) so the new poller code runs; the server side
  takes effect with the next server start.
- No change to any tool, whitelist, limit or protection; token authentication, Host/Origin checks and announcement file
  permissions are as before. Prepares the ground for an upcoming desktop app that starts and stops its own server.

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

## 0.13.0 — export, named versions, comparison, region analysis

- New tool `lr_export`: exports one photo as a JPEG (as it looks now) at the original size or a chosen size, to the place the
  USER names in the chat (`folder`, an absolute path, or `destination` desktop / pictures / documents). This is the one place
  where the plug-in takes a path from a request, so it is checked there: the folder must exist (nothing is created), no network
  paths, no `..`, nothing under system folders, AppData, `.ssh` or this tool's own data folder; only JPEG, the file name is made
  from the photo's name, and a file is never overwritten. The tool text tells the assistant to use only a place the user said.
  Not sent to the AI service. See SECURITY.md for the remaining risks.
- New tools `lr_save_version`, `lr_list_versions`, `lr_apply_version`, `lr_delete_version`: named versions of one photo (all
  settings this project may change, with a small preview picture) kept in `~/LrMcp/knowledge/versions/`. Going back to a version is
  one undoable change that is not held to the per-call limits.
- New tool `lr_compare`: the current look and the saved versions side by side in one picture with letters, numbers and differences.
- The preview numbers now include a 3x3 grid (brightness, colour, saturation per region) and the "sky-like blue" (share, mean hue,
  mean saturation), so "not blue enough" can be measured.
- Fix: the time stamp in preview file names used `%d` and saturated at -2147483648; it is now correct.
- Measured: the preview's file size is NOT a proof of identical pictures (the JPEG embeds the changing file name, so equal pixels
  can differ by a few bytes); the acceptance scripts now compare pixels.
- 22 tools in total. Tests: 172 unit tests; real-Lightroom runs on the test catalog: the new `acceptance_export_versions.py`
  (export at full size and 1024 px, no overwrite, the user-named folder and the refusals, versions, comparison, region numbers)
  and the write, catalog-information, presets, batch and review runs all pass.

## 0.12.0 — restore protection, before/after previews, review (pull request #2 by Galio1991)

- `lr_restore` and `lr_restore_original` refuse by default to overwrite a setting that was changed after the edit
  (also by hand in Lightroom), for develop changes, presets, catalog information and batches. `force=true` overwrites after
  the user has agreed; `lr_restore_original(dry_run=true)` lists the conflicts. Settings that Lightroom rewrites by itself
  (for example the preset value `LensBlur`) are not counted as conflicts. Restoring an older edit after a newer edit touched
  the same setting is also a conflict now: undo in reverse order.
- `preview=true` on `lr_set_develop` and `lr_apply_preset` returns a before and an after preview and the numeric
  differences (brightness, clipped highlights / shadows, warm-cool index).
- New tool `lr_review_selected` (read-only): previews and numbers for up to 10 selected photos in one reply, to choose picks.
- New tool `lr_plan_from_edit` (read-only): turns a verified single-photo slider edit into a dry-run batch plan for the other
  selected photos (source photo excluded, crop and curves skipped); it is executed with `lr_batch_set_develop` and its plan id.
- 16 tools in total. Tests: 151 unit tests; real-Lightroom runs on the test catalog: write, catalog information, presets, batch
  and the new `acceptance_review.py` (multi-photo review, before/after, conflict refusal and `force`, reusing an edit) all pass.
- The contributor also reports an iPhone ProRAW DNG white-balance edit and restore on Lightroom Classic 15.0; we have not
  reproduced it (待验证).

## 0.11.2 — fixes from a contributor (pull request #1 by Galio1991)

- A write that Lightroom applied but whose reply timed out is no longer recorded as "failed": the record is kept as
  "uncertain" with the old values (or the whole saved state for presets, and the keyword changes for catalog
  information), so `lr_restore` can still undo it.
- `lr_restore_original` now uses the first saved value of a setting even when an earlier change of that setting was restored
  on its own.
- A batch plan re-reads every photo just before writing and stops for a photo that was changed after the dry run.
- The announcement and token files are now given "modify" rights for the current user (still only that user), so the
  server can remove them again, for example after the data folder was moved.
- Test scripts: the write acceptance script no longer deletes a read-only switch file that was already there; the read
  acceptance script accepts JPEGs without exposure data; the smoke test prints the doctor report safely on GBK consoles.
- Checked before merging: the 141 unit tests, the write, catalog-information, batch and read acceptance runs against a real
  Lightroom test catalog, and the read-only-switch fix. The preset acceptance run could not be completed (not verified
  on the timed-out preset path beyond the unit tests).

## 0.11.1 — bilingual tool descriptions

- The description of every one of the 14 tools (and the server instructions) is now English first, Chinese second. English is
  the safest common language for Claude, Codex and other clients; the Chinese text stays for Chinese-speaking users. A test checks it.
- The `lr_set_develop` description was out of date (it still said that curves and crop are not supported); it now lists
  everything that can be changed and says what cannot (masks).
- `lr_restore` / `lr_restore_original` descriptions say what they cover (catalog information is restored with `lr_restore`).
- `AI_GUIDE.md` is now written in English (with a note to answer in the user's language and to translate the Chinese tool
  messages); it also mentions the installer and the update notice.

## 0.11.0 — catalog information

- New tools `lr_get_metadata` and `lr_set_metadata` (14 tools in total): rating (0–5), flag (pick / none / reject), colour label,
  title (200 characters), caption (1000 characters) and keywords (add / remove, up to 10 per call, new keywords are created at
  the top level). One photo at a time; the old values are saved first and `lr_restore` writes back only what was changed.
  Keywords created by a change stay in Lightroom's keyword list after a restore (the SDK cannot delete keywords).
- Measured: Lightroom reports "no colour label" as `gray`; this is shown as `none`.
- Masks are NOT supported. Experiment 11 measured that mask data written through `applyDevelopSettings` is discarded when the
  photo is loaded into the develop engine, and that reads of the active photo do not show masks, so a mask feature could not
  be made reliable. The code was removed again; the measurement scripts stay in the development folder.
- Real-Lightroom acceptance run (`acceptance_metadata.py`) on a RAW of the test catalog: write, read back, two-step restore
  and final state identical to the start.

## 0.10.0 — batch changes

- New tool `lr_batch_set_develop` (12 tools in total): adds the same RELATIVE change to the sliders of up to 10 photos.
  Two steps: a dry run (default; changes nothing, returns each photo's before / after numbers, the photos that would be
  skipped and a single-use plan id valid for 15 minutes) and the real run, which needs that plan id.
- Each photo goes through the normal guarded single-photo write (range, step, readonly switch, old values saved first) and
  gets its own record; one batch record ties them together and `lr_restore(batch_id)` undoes the whole batch (or one photo
  by its own edit id). The run stops at the first failure; what was done stays and can be restored.
- Not in a batch: crop, straighten and curves (they need a look at every photo). White balance is allowed; JPEGs are
  skipped with the reason.
- No plug-in change. Real-Lightroom acceptance run (`acceptance_batch.py`) on two RAW and one JPEG of the test catalog:
  dry run changes nothing, exact relative changes, plan single use, one restore undoes everything, full settings snapshots
  identical at the end.

## 0.9.0 — develop presets

- New tools `lr_list_presets` (search the presets in Lightroom) and `lr_apply_preset` (apply one to a photo). 11 tools in total.
- Presets are applied by Lightroom itself. Before that the photo's whole settings are saved to disk; afterwards the plug-in
  reports every setting that changed (also the ones the preset does not list) and `lr_restore` / `lr_restore_original` write
  the old values back, also when presets and slider changes are mixed.
- Presets with masks / AI local adjustments, and photos that already have masks, are refused.
- New plug-in commands `list_presets`, `snapshot`, `apply_preset`, `restore_settings` (the last accepts only keys the photo
  already has, with the same type and inside the known ranges, never masks) and a strict JSON decoder.
- Measured (experiment 10): of 381 presets 38 carry masks and most others touch settings beyond our sliders (looks, camera
  profiles, black & white mixer), so presets are applied natively. Lightroom creates internal values on first use
  (`GrainSeed`, `DepthMapInfo`, ...) that cannot be deleted; they do not change the picture as far as measured.
- Real-Lightroom acceptance run (`acceptance_presets.py`) on a RAW and a JPEG of the test catalog: the full settings snapshot
  (about 170 keys, tables included) is identical after restore.
- Not included: the preset amount slider (0–200) and applying to several photos at once.

## 0.8.0 — crop and straighten

- `lr_set_develop` can change the four crop edges (`CropLeft`, `CropTop`, `CropRight`, `CropBottom`, fractions of the image;
  uncropped is 0, 0, 1, 1) and `CropAngle` (straighten, ±45°, at most ±10° per call). 89 sliders in total.
- The crop must keep at least 10% of the width and of the height, with left < right and top < bottom; checked on the
  final rectangle by both the server and the plug-in. Restoring puts the old edges back and the photo is uncropped again.
- Measured (experiment 9): Lightroom stores out-of-range or inverted edges unchecked and then shows the photo as not cropped;
  angles beyond ±45° stop working; writing the aspect-ratio lock leaves a side effect behind, so it is not allowed.
- Which way a positive `CropAngle` turns is not confirmed (待验证); the tool text tells the assistant to check the preview.
- Real-Lightroom acceptance run on a RAW and a JPEG of the test catalog: all checks pass, everything restored.

## 0.7.0 — detail and effects

- 22 more sliders in `lr_set_develop` (84 in total): sharpening (amount, radius, detail, masking), noise reduction (luminance
  and colour, with their detail / contrast / smoothness), post-crop vignette (amount, midpoint, feather, roundness,
  highlight contrast), lens vignette (amount, midpoint), grain (amount, size, roughness), defringe (purple, green).
- Measured (experiment 8): Lightroom stores out-of-range values unchecked for all of these, so the ranges are checked by
  the server and the plug-in. The vignette "style" option is not included.
- Real-Lightroom acceptance run on a RAW and a JPEG of the test catalog: all checks pass, everything restored.

## 0.6.0 — colour grading, calibration, tone curves

- `lr_set_develop` can now change 25 more sliders: colour grading (shadows / midtones / highlights / global hue,
  saturation, luminance, balance, blending), camera calibration (shadow tint, red / green / blue hue and saturation) and
  the parametric tone curve (shadows, darks, lights, highlights). 62 sliders in total. Hue values are cyclic (no step limit).
- Point curves: `ToneCurvePV2012` (luminance) and its Red / Green / Blue versions, given as `[[x, y], ...]`
  (2–16 points, first x = 0, last x = 255, x increasing, y never going back, at most 90 away from the straight line).
  Old curves are saved and restored like the sliders.
- Measured (experiment 7): the new sliders reset to their default when given an out-of-range value (instead of storing it
  as the older sliders do); point curves can be written and restored exactly; the three parametric split points did not
  take writes and are not supported (reason not found: 待验证).
- Real-Lightroom acceptance run on a RAW and a JPEG of the test catalog: all checks pass, everything restored.

## 0.5.0 — white balance (RAW)

- `lr_set_develop` can change `Temperature` (2000–50000 K, at most ±1000 per call) and `Tint` (±150, at most ±30 per call)
  on RAW photos. The white balance label becomes "Custom"; restoring writes the old label and numbers back.
- JPEGs (no kelvin values) and RAW files whose temperature cannot be read are refused with a clear message.
- Measured (experiment 6): Lightroom stores any temperature/tint value unchecked, JPEG values never read back, and a
  restore must write the label together with the numbers. An unedited RAW whose temperature cannot be read is refused
  (not measured on a real unedited RAW: 待验证).
- Real-Lightroom acceptance run on a RAW and a JPEG of the test catalog: all checks pass, everything restored.

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
