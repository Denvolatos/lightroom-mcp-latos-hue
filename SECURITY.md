# Security

## What this software can and cannot do

- **Since 0.2 it can change a small set of sliders** (exposure, the ten global sliders, 24 HSL values; nothing else: no
  white balance, tone curve, masks, crop, presets, metadata, no deleting, no import/export). Every change is limited by
  range and by a step per call, one photo at a time, and the old values are saved first (`C:\Users\<you>\LrMcp\edits`)
  so it can be restored. A **read-only switch** (file `C:\Users\<you>\LrMcp\readonly`) makes the server and the plug-in
  refuse every change. Version 0.1 was read-only.
- Other files it writes: preview JPEGs in `C:\Users\<you>\LrMcp\previews` (never added to your catalog), a token, a
  port/log file and the saved change records, all in `C:\Users\<you>\LrMcp`.
- **Back up your catalog before using the change tools on real work.** An AI assistant that can change sliders can make
  a photo look worse; restoring writes the saved values back (it overwrites a value you changed by hand afterwards).
- Everything runs on your own computer. The Python server listens on `127.0.0.1` only, with an exclusive bind
  (no other process can share the port). Nothing is sent over the internet by this project. **Note:** the preview
  images and photo information that the tools return go to whichever AI service you connect (Claude, Codex, ...);
  that is how it works, so only use it with photos you are happy to share with that service.
- Requests between the Lightroom plug-in and the server need a random token (regenerated on every server start,
  stored in a file that only your Windows user should read), a correct `Host` header, and are refused if they carry
  an `Origin` header (which browsers add), so a web page cannot talk to the server.
- The plug-in runs a fixed whitelist of commands. It never takes a file path from a request, and for changes it checks the
  slider whitelist, the range, the step size and the read-only switch itself, without trusting the server.
- Development builds contain a **development bridge** (`DevRun.lua`, `devscripts/`, `server/dev_bridge.py`) that can run
  Lua scripts from the plug-in's own folder. It is active only while `~/LrMcp/dev_enabled` exists, which only the
  development server creates. Release builds do not contain it. If you copy the plug-in folder by hand, delete
  `DevRun.lua` and `devscripts/`.

## Known limits

- Any program running as your Windows user can read the token file and talk to the server (the usual limit of local
  tools). The token file's permissions are tightened on a best-effort basis (`icacls`) and not yet verified.
- Several servers (one per AI session) can run at once, on ports 58770–58789; the plug-in only polls that range, and each server has its own random token.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** ("Security" tab → "Report a vulnerability"). If that is not
available to you, open an issue that says you have a security report **without details**, and I will arrange a private
channel. Please do not publish details before a fix is available.
