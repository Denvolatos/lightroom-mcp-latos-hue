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
