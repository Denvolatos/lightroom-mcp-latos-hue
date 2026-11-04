<!-- 草稿：给项目所有者审阅，发布时确认后再贴到 GitHub Release（标签 hue-v1.0.0）。 -->
# Latos Hue 1.0.0 — 首个发布版 / First release

## 中文

Latos Hue（修图助手）是一个 Windows 桌面软件：在一个窗口里导入照片、挑片、让 AI 帮你修图、再导出，Adobe Lightroom Classic 在后台当修图引擎。

### 新增了什么（这是首个发布版）
- **导入：** 从存储卡或任意文件夹选照片，复制一份到软件工作文件夹（原片不动），并加进 Lightroom 目录。
- **图库选片：** 按文件夹分组浏览缩略图，搜索、筛选、排序、多选。
- **AI 挑片：** 比较选中的照片，给出排名和星级、旗标建议；你确认后才写入。
- **AI 修图：** 用对话让 AI 调整照片；可开"逐项确认"，每一步都能撤销，也能一键还原到修图前。
- **预设、经验、收藏：** 都只保存在你自己的电脑上。
- **导出：** JPEG 或 TIFF（8 / 16 位），自己选文件夹和尺寸，不覆盖已有文件。
- **自动启动 Lightroom、环境检查向导、检查更新**（只提示，不自动安装）。
- **AI 来源：** Claude（调用已登录的 Claude Code 命令行）和 Codex（调用已登录的 Codex 命令行）。
- **免 Python 安装包**，不需要管理员权限，会同时装好 Lightroom 插件。

### 怎么安装
1. 下载下面的 `LatosHue-Setup-1.0.0.exe`，核对 SHA-256。
2. 在你自己的资源管理器里双击运行（不要通过 Claude 桌面版启动）。
3. **装完重启 Lightroom。** 第一次打开软件，按"环境检查"清单的提示做。

系统要求：Windows 10 / 11；已安装 Lightroom Classic；已安装并登录的 Claude Code 或 Codex 命令行。

### 隐私
照片原片只在本机处理；修图时选中照片的预览会发送给你选择的 AI 服务；软件不保存你的账号、不代你登录；检查更新只访问 GitHub、不发送个人信息，可在设置里关闭。

### 已知限制
- 只支持 Windows；需要 Lightroom Classic 和已登录的 Claude Code 或 Codex 命令行。
- 安装包**没有代码签名**，Windows SmartScreen 可能提示"未知发布者"，可点"更多信息"→"仍要运行"。
- 下列情况尚未在真机上充分验证：Windows 125% / 150% 缩放下的外观；100 张以上的大批量导入和真实存储卡；原始尺寸的 16 位 TIFF 导出。
- 导出只有 JPEG 和 TIFF，没有 PNG；没有 Mac 版；"多版本"对比页暂未提供。

### 校验信息
| 项目 | 值 |
|---|---|
| 文件名 | `LatosHue-Setup-1.0.0.exe` |
| 大小 | 23,801,828 字节（约 22.7 MiB） |
| SHA-256 | `073F77EDD3E3E8E375663B87D8D5B64C7332CF4E8EE4FB5D1D3EE5761387034F` |

校验方法（PowerShell）：`Get-FileHash .\LatosHue-Setup-1.0.0.exe -Algorithm SHA256`

许可证：AGPL-3.0-only。本软件不含任何 Adobe 软件，也不是 Adobe 官方产品。第三方许可证随安装包放在程序目录下。

## English

Latos Hue is a Windows desktop app: import photos, pick the best ones, let an AI retouch them, and export, all in one window. Adobe Lightroom Classic works in the background as the editing engine.

### What is new (this is the first release)
- **Import** photos from a memory card or any folder: copied to the app's work folder (originals untouched) and added to your Lightroom catalog.
- **Gallery** with folder groups, search, filters, sorting and multi-select.
- **AI photo picking:** ranks the selected photos and suggests stars and flags; written only after you confirm.
- **AI retouching** by chat; optional "confirm each step", every step can be undone, one click returns to the state before retouching.
- **Presets, experience notes, favourites**, kept only on your own computer.
- **Export** to JPEG or TIFF (8 / 16 bit); you choose folder and size; existing files are never overwritten.
- **Optional automatic start of Lightroom, an environment-check wizard, and an update check** (it only tells you).
- **AI sources:** Claude (the signed-in Claude Code command line) and Codex (the signed-in Codex command line).
- **No-Python installer**, no administrator rights, installs the Lightroom plug-in too.

### How to install
1. Download `LatosHue-Setup-1.0.0.exe` below and compare the SHA-256.
2. Double-click it from your own File Explorer (not from a shell started by Claude Desktop).
3. **Restart Lightroom after installing.** On first launch, follow the "environment check" list.

Requirements: Windows 10 / 11; Lightroom Classic installed; the Claude Code or Codex command line installed and signed in.

### Privacy
Original photos are processed on your computer only. When you retouch, a preview of the selected photos is sent to the AI service you chose. The app does not store your account or sign in for you. The update check only contacts GitHub, sends no personal information, and can be turned off in Settings.

### Known limitations
- Windows only; needs Lightroom Classic and a signed-in Claude Code or Codex command line.
- The installer is **not code-signed**; Windows SmartScreen may show "unknown publisher" (click "More info", then "Run anyway").
- Not yet verified well enough on real machines: the look at 125% / 150% scaling; bulk imports of 100+ photos and real memory cards; full-size 16-bit TIFF export.
- Export is JPEG and TIFF only (no PNG); no Mac version; the "multiple versions" comparison page is not available yet.

### Checksums
| Item | Value |
|---|---|
| File name | `LatosHue-Setup-1.0.0.exe` |
| Size | 23,801,828 bytes (about 22.7 MiB) |
| SHA-256 | `073F77EDD3E3E8E375663B87D8D5B64C7332CF4E8EE4FB5D1D3EE5761387034F` |

Verify (PowerShell): `Get-FileHash .\LatosHue-Setup-1.0.0.exe -Algorithm SHA256`

License: AGPL-3.0-only. This software contains no Adobe software and is not an Adobe product. Third-party licenses are installed in the program folder.
