# 安全说明

（English version below / 英文版在下方）

## 这个软件能做什么、不能做什么

- **0.2 起能修改少数滑块**（曝光、十个全局滑块、24 个 HSL 值，以及 RAW 照片的色温/色调；其他都不动：不碰色调曲线、蒙版、裁剪、预设、元数据，不删除，不导入导出）。每次修改都有范围限制和单次限幅，一次只改一张照片，**改之前先把旧值存到** `C:\Users\<你>\LrMcp\edits`，随时可还原。**只读开关**（文件 `C:\Users\<你>\LrMcp\readonly`）会让服务和插件拒绝一切修改。0.1 版是纯只读。
- 它还会写的文件：预览 JPEG（`LrMcp\previews`，不会加入你的 Lightroom 目录）、口令、端口/日志文件和修改记录，都在 `C:\Users\<你>\LrMcp`。
- **在真实作品上用修改功能前，请先备份目录。** 能改滑块的 AI 也可能把照片改难看；还原会写回保存的旧值（会覆盖你之后手动改过的同一个值）。
- 所有东西都在你自己的电脑上运行。Python 服务只监听 `127.0.0.1`，且独占端口。除下面的更新提醒外，本项目不会通过网络发送任何东西。**注意：** 工具返回的预览图和照片信息会发给你连接的 AI 服务（Claude、Codex 等），这是它的工作方式，所以只对愿意分享给该服务的照片使用。
- 插件和服务之间的请求需要随机口令（每次服务启动重新生成）、正确的 `Host` 头，并且带 `Origin` 头（浏览器会加）的请求一律拒绝，所以网页无法和服务通信。
- 插件只运行固定白名单里的命令，从不接收请求里的文件路径；修改时插件自己再检查滑块白名单、范围、单次限幅和只读开关，不信任服务。
- 开发版包含**开发通道**（`DevRun.lua`、`devscripts/`、`server/dev_bridge.py`），只在 `~/LrMcp/dev_enabled` 存在时才启用，发布版不含它。手动复制插件文件夹的话，请删掉 `DevRun.lua` 和 `devscripts/`。

## 更新提醒（唯一的联网行为）

服务每天最多向 GitHub 公开接口询问一次本项目的最新版本；如果比已安装的新，`lr_status` 会多一行提示。这是匿名的 HTTPS 请求，超时 5 秒，不发送任何关于你、你的照片或 Lightroom 的信息（GitHub 能看到你的 IP 和 User-Agent `lrmcp/<版本>`）。不会自动下载或安装。关闭方法：设环境变量 `LRMCP_NO_UPDATE_CHECK=1`，或在 `C:\Users\<你>\LrMcp\` 下建一个空文件 `no_update_check`。

## 已知局限

- 以你的 Windows 用户运行的任何程序都能读口令文件并和服务通信（本机工具的通病）。口令文件的权限用 `icacls` 尽力收紧，尚未验证。
- 可同时运行多个服务（每个 AI 会话一个），端口 58770–58789；插件只轮询这个范围，每个服务有自己的随机口令。

## 报告漏洞

请用 GitHub 的**私密漏洞报告**（"Security" 标签 → "Report a vulnerability"）。用不了的话，请开一个 issue，只说明"我有安全问题要报告"，**不要写细节**，我会安排私下渠道。修复发布前请不要公开细节。

---

# Security

## What this software can and cannot do

- **Since 0.2 it can change a small set of sliders** (exposure, the ten global sliders, 24 HSL values, and temperature/tint of RAW photos; nothing else: no
  tone curve, masks, crop, presets, metadata, no deleting, no import/export). Every change is limited by
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

## Update notice (the only internet access)

Once a day the server asks GitHub's public API for the latest release of this project and, if it is newer than the
installed version, `lr_status` shows a one-line notice. It is an anonymous HTTPS GET with a 5-second timeout; nothing
about you, your photos or Lightroom is sent (GitHub sees your IP address and the User-Agent `lrmcp/<version>`).
Nothing is downloaded or installed automatically. Switch it off by setting `LRMCP_NO_UPDATE_CHECK=1` or by creating an
empty file `C:\Users\<you>\LrMcp\no_update_check`.

## Known limits

- Any program running as your Windows user can read the token file and talk to the server (the usual limit of local
  tools). The token file's permissions are tightened on a best-effort basis (`icacls`) and not yet verified.
- Several servers (one per AI session) can run at once, on ports 58770–58789; the plug-in only polls that range, and each server has its own random token.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** ("Security" tab → "Report a vulnerability"). If that is not
available to you, open an issue that says you have a security report **without details**, and I will arrange a private
channel. Please do not publish details before a fix is available.
