# 安全说明

（English version below / 英文版在下方）

## 这个软件能做什么、不能做什么

- **目录信息的修改：** 星级、旗标、颜色标签、标题、说明、关键词（一次一张照片，限制长度，旧值先存盘，可还原；不能删除关键词本身，也不碰其他元数据）。
- **导出（`lr_export`）：** 插件原来"从不接收请求里的路径"，导出这一条是例外：为了让你在对话里说放哪就放哪，AI 会把你说的文件夹路径传给插件。插件**不信任**它：必须是本机已存在的文件夹（不替你创建），拒绝网络路径、`..`、系统目录、AppData、`.ssh` 和本工具自己的数据目录；只写 JPEG，文件名由照片名生成，**绝不覆盖已有文件**。工具说明要求 AI 只用你亲口说的路径。**仍然存在的风险：** 如果 AI 被网页里的恶意内容诱导，它可能把照片导到你电脑上某个允许的文件夹；映射成本机盘符的网络盘（比如 Z:）插件分辨不出来。导出的文件不会发给 AI 服务；只读开关不拦导出（导出不改照片）。
- **导入命令（只供桌面软件，不是 AI 工具）：** 这是插件除导出外第二个从请求里接收路径的地方，路径来自本机的桌面软件，不开放给 AI（MCP 工具列表里没有它，测试会检查）。插件重新校验：必须是本机已存在的文件（不是文件夹），只接受常见照片格式（jpg/jpeg/arw/cr2/cr3/nef/nrw/raf/orf/rw2/dng/tif/tiff/heic/heif/png），拒绝网络路径、`..`、系统目录、AppData、`.ssh` 和本工具自己的数据目录；只“添加不移动”，不复制、不删除、不覆盖任何文件，不套预设。已在目录里的照片不会重复添加。只读开关会拦截它。**仍然存在的风险：** 如果有恶意进程冒用了口令，它可以把你电脑上任意位置的照片文件加进目录（口令只在本机、仅当前用户可读）；映射成本机盘符的网络盘（比如 Z:）插件分辨不出来。
- **命名版本：** 保存在 `C:\Users\<你>\LrMcp\knowledge\versions\`（每张照片一个文件夹，最多 50 个版本），只含本项目能改的参数和一张小预览图，不联网、不上传。回到某个版本是一次普通的修改（受只读开关约束，可撤销）。
- **多张照片的预览：** `lr_review_selected` 一次把最多 10 张选中照片的预览图发给你正在用的 AI 服务（和单张预览一样，只在本机生成，发给 AI 服务的是图片本身）；只读，不改任何东西。
- **批量修改的限制：** 一次最多 10 张；必须先预演（预演什么都不改），再用预演返回的一次性编号执行（15 分钟有效）；只做滑块的相对改动，不做裁剪/曲线；遇到第一个失败就停止；每张照片各自存旧值，可单张或整批还原。
- **预设的还原机制：** 套预设时，整张照片的设置先存盘；还原时插件只接受“照片当前已有、类型相同、在已知范围内”的项，永远不接受蒙版。Lightroom 自己生成的内部值（如 GrainSeed）还原不掉，不影响画面。
- **受保护的修改：**可修改白名单内的调整参数、目录信息，并套用不带蒙版的开发预设；不碰蒙版，不删除或导入导出照片。调整参数有范围和单次限幅，修改前把旧值存到 `C:\Users\<你>\LrMcp\edits`。**只读开关**（文件 `C:\Users\<你>\LrMcp\readonly`）会让服务和插件拒绝一切修改。0.1 版是纯只读。
- 它还会写的文件：预览 JPEG（`LrMcp\previews`，不会加入你的 Lightroom 目录）、口令、端口/日志文件和修改记录，都在 `C:\Users\<你>\LrMcp`。
- **在真实作品上用修改功能前，请先备份目录。** 还原前会检查这些参数之后有没有被改过（包括你在 Lightroom 里手动改的），发现冲突时默认拒绝覆盖；用户明确确认后可用 `force=true` 覆盖。
- Lightroom 会自行规范化部分预设参数（如 `LensBlur`）；这些参数的后续手动改动无法可靠识别冲突。还原预设前请先查看照片及预演结果。
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

- **Guarded changes:** it can change whitelisted develop settings and catalog metadata, and apply presets without masks.
  It cannot edit masks, delete photos, or import/export. Develop changes have range and step limits, and old values are
  saved before a write (`C:\Users\<you>\LrMcp\edits`) for restoration. A **read-only switch** (file
  `C:\Users\<you>\LrMcp\readonly`) makes the server and plug-in refuse every change. Version 0.1 was read-only.
- **Export (`lr_export`):** the plug-in used to take no path from a request; export is the one exception, so that a photo goes
  where the user says in the chat: the assistant passes the folder the user named. The plug-in does **not** trust it: it must be an
  existing local folder (nothing is created), network paths, `..`, system folders, AppData, `.ssh` and this tool's own data folder are
  refused; only JPEG is written, the file name is made from the photo's name and **nothing is ever overwritten**. The tool text tells the
  assistant to use only a place the user said. **Remaining risk:** an assistant tricked by malicious web content could export photos
  into some allowed folder; a network drive mapped to a local letter (such as Z:) cannot be told apart from a local one. Exported files
  are not sent to the AI service; the read-only switch does not block export (it changes no photo).
- **Import command (desktop app only, not an AI tool):** after export, this is the second place where the plug-in takes a path from a request. The path comes from the desktop app on this computer, and the command is not offered to the AI (it is not in the MCP tool list; a test checks that). The plug-in re-checks it: an existing local file (not a folder), a common photo extension only (jpg jpeg arw cr2 cr3 nef nrw raf orf rw2 dng tif tiff heic heif png), and network paths, `..`, system folders, AppData, `.ssh` and this tool's own data folder are refused. It only "adds without moving": nothing is copied, deleted or overwritten and no preset is applied. A photo already in the catalog is not added twice. The read-only switch blocks it. **Remaining risk:** a malicious process that got hold of the token could add any photo file on this computer to the catalog (the token stays on this machine and is readable only by the current user); a network drive mapped to a local letter (such as Z:) cannot be told apart from a local one.
- **Named versions:** kept in `C:\Users\<you>\LrMcp\knowledge\versions\` (one folder per photo, at most 50 versions): only the settings this project may change
  plus a small preview picture; no network. Going back to a version is an ordinary change (subject to the read-only switch, undoable).
- Other files it writes: preview JPEGs in `C:\Users\<you>\LrMcp\previews` (never added to your catalog), a token, a
  port/log file and the saved change records, all in `C:\Users\<you>\LrMcp`.
- **Back up your catalog before using the change tools on real work.** Before restoring, the tools check for later changes
  (also manual ones) and refuse conflicting writes by default; `force=true` overwrites only after explicit review.
- Lightroom normalizes some preset settings, such as `LensBlur`. Later manual changes to these settings cannot be
  detected reliably, so inspect the photo and restoration plan before restoring a preset.
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
