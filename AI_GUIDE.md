# 🤖 给 AI 助手的说明 / Guide for AI assistants

> **如果你是 AI 助手**，用户把这个仓库的链接发给了你，让你帮他安装并使用这个软件：请**完整读完本文件**，再按步骤做。
> 需要用户亲自操作的地方（点 Lightroom 的界面、重启软件），请告诉他具体怎么点，并等他回复。请用**用户使用的语言**和他交流。
> 你**不需要**读完整个仓库，本文件就是为你写的。

**English summary.** This repo is a Lightroom Classic plug-in (Lua) plus a small MCP server (Python, stdio).
It lets an AI assistant see the photo the user selected in Lightroom (develop settings, a preview image, histogram
numbers) and, since 0.2, make **small, guarded slider changes that can be undone**. Windows only for now (macOS, Photoshop, Premiere are not supported yet). Install: `pip install` the `server`
folder from the GitHub zip, copy the plug-in folder into Lightroom's `Modules` folder, register the server with the
AI client as a local stdio MCP server, restart both. Verify with the tool `lr_status`; diagnose with `lr_doctor`.
Details below (in Chinese, but all commands are language-neutral).

---

## 1. 这是什么

一个让 AI 能"看"用户在 Adobe Lightroom Classic 里选中的照片的小工具，由两部分组成：

- **Lightroom 插件**（Lua）：在 Lightroom 里运行，只执行固定的白名单命令。
- **MCP 服务**（Python，命令 `lrmcp`）：通过 stdio 连接 AI 客户端，并在本机（`127.0.0.1`）和插件通信。

当前版本 **0.4.0**：能读照片信息、读取调整参数、生成预览图并给出直方图数字；也能对**少数滑块做小步、受保护的修改**，并随时还原。
白平衡、色调曲线、蒙版、裁剪、预设、元数据都**不能**改，也不能删除照片或导入导出。

## 2. 先确认条件（不满足就别硬装）

| 条件 | 怎么查 |
|---|---|
| Windows 10/11 | macOS 暂不支持（计划中）；Photoshop、Premiere 也暂不支持 |
| 已安装 Adobe Lightroom Classic，且能正常打开 | 在 Lightroom 里 *帮助 → 系统信息* 看版本；开发和测试用的是 15.2 |
| Python 3.10 或更新 | 运行 `python --version`。没有的话请用户去 python.org 安装，勾选"Add to PATH" |
| 你所在的 AI 应用能添加**本地 stdio MCP 服务** | **Claude Code 已实测可用**；Codex 的登记命令已写好但**没有实测**（见下）。其他应用（WorkBuddy、豆包、MiMo 系客户端、Cursor 等）**也没有验证过**：只要它能添加"命令 + 参数"形式的本地 MCP 服务，就用第 3 步的通用写法；如果它只能连云端、不能运行本机命令，就如实告诉用户"目前用不了"，不要尝试绕过 |

## 3. 安装

**重要（给在 Claude 桌面版里运行命令的助手）**：Claude 桌面版是 Windows 商店（MSIX）应用，它启动的程序写入 `AppData` 时会被悄悄重定向，Lightroom 看不到。所以**第 3.2 步（复制插件）请让用户在他自己的 PowerShell 里运行**，不要在你自己的 shell 里运行。

### 3.1 安装 MCP 服务（Python）

```powershell
pip install "https://github.com/Denvolatos/lightroom-mcp-win/archive/refs/heads/main.zip#subdirectory=server"
lrmcp --version
```

期望输出形如 `lightroom_mcp 0.4.0`（版本号可能更新）。如果提示找不到 `lrmcp`，说明 Python 的 Scripts 目录不在 PATH 里：用 `python -m pip show -f lightroom-mcp` 找到它，或者以后一律用 `python -m lightroom_mcp` 代替 `lrmcp`，并在登记时写 Python 的**绝对路径**。

### 3.2 安装 Lightroom 插件（让用户在自己的 PowerShell 里运行）

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

应该列出 8 个文件（`Bridge.lua`、`Commands.lua`、`Info.lua`、`Init.lua`、`Json.lua`、`Status.lua`、`Stop.lua`、`Version.lua`），**没有** `DevRun.lua` 和 `devscripts`（那是开发用的，不要装）。
然后请用户**重启 Lightroom**。重启后在 *文件 → 增效工具管理器* 里应看到 **LrMCP** 且已启用；如果没有，选 *添加*，指向 `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`。

### 3.3 把服务登记到你的 AI 客户端

**这会修改用户的客户端配置，先说明再做，并先问用户同意。**

- **Claude Code / Codex**（本机命令行里有 `claude` 或 `codex`）：
  ```powershell
  lrmcp register --dry-run   # 先看会做什么，不改任何东西
  lrmcp register             # 用户同意后再运行
  ```
  它通过 `claude mcp add` / `codex mcp add` 登记名为 `lightroom_mcp` 的服务。（Codex 没在作者的电脑上测试过。）
- **其他支持"本地 MCP 服务"的应用**：添加一个 stdio 服务，名字 `lightroom_mcp`，命令是 `lrmcp` 的**绝对路径**（用 `where lrmcp` 查），参数为空。常见的配置文件写法：
  ```json
  { "mcpServers": { "lightroom_mcp": { "command": "C:\\完整路径\\lrmcp.exe", "args": [] } } }
  ```
  没有 `lrmcp.exe` 时：`"command": "C:\\完整路径\\python.exe", "args": ["-m", "lightroom_mcp"]`。
  配置文件的位置和格式因应用而异，请按你自己所在应用的文档来；**注意名字用下划线 `lightroom_mcp`**（有的应用对别的写法会静默忽略）。

### 3.4 重启并验证

1. 请用户**重启你所在的 AI 应用**（让它加载新的 MCP 服务），并保持 **Lightroom 已打开**。
2. 请用户在 Lightroom 里**打开一个目录并选中一张照片**。
3. 调用工具 **`lr_status`**：应返回 `"connected": true`、Lightroom 版本和目录名。
4. 如果不是，调用 **`lr_doctor`**，按它给出的中文提示处理（见第 6 节）。

## 4. 怎么用（9 个工具：5 个只读，4 个与修改有关）

| 工具 | 用途 |
|---|---|
| `lr_status` | Lightroom 是否连上、版本、目录、是否有选中照片 |
| `lr_list_selected` | 选中的照片：文件名、格式、评分、尺寸、ISO/光圈/快门/焦距/镜头/机身、`id` |
| `lr_get_develop` | 一张照片当前的调整参数（曝光、对比度、高光、阴影、白平衡、HSL 等）。`photo` 填 `"selected"` 或 `lr_list_selected` 返回的 `id` |
| `lr_get_preview` | 预览图（长边 256–2048 像素，默认 1024）加直方图数字：平均亮度、过曝/欠曝比例、冷暖偏向 |
| `lr_doctor` | 自检，用中文说明哪里有问题、怎么处理 |
| `lr_set_develop` | **修改**一张照片的滑块：`changes` 填 `{参数名: 目标数值}`，例如 `{"Exposure2012": 0.3, "Highlights2012": -20}`；`reason` 写一句理由；`preview` 为 true 时改完顺便返回预览图。允许的参数、范围和单次最多改多少写在工具说明里 |
| `lr_restore` | 还原一次修改（`edit_id` 来自 `lr_set_develop` 的返回或 `lr_list_edits`）：把那次修改碰过的滑块写回旧值 |
| `lr_restore_original` | 让一张照片回到 LrMCP 第一次改它之前的样子；`dry_run` 为 true 时只显示会写回什么 |
| `lr_list_edits` | 列出 LrMCP 做过的修改记录 |

**典型用法**：用户说"看看这张照片哪里有问题"→ 先 `lr_list_selected`，再 `lr_get_preview`（看图 + 数字），必要时 `lr_get_develop` 看已经做过哪些调整，然后用大白话告诉用户：偏暗/偏亮、高光是否过曝、暗部是否死黑、色调偏冷还是偏暖，并说明依据（引用返回的数字）。
**调色老师式的回答更有帮助**：说"改了会怎样"，而不是只给参数；用户可能是调色新手。

**注意**：`lr_get_develop` 里 RAW 照片在没编辑过时读不到 Temperature/Tint，只显示 `WhiteBalance`；这不代表没有色温。**白平衡（色温/色调）目前不能改**：用户要调白平衡时，请如实说明现在做不到，可以给出建议，让用户在 Lightroom 里自己拖。

### 修改照片的规矩（请严格遵守）

1. **只在用户明确要求时才改**，只改用户指定的那一张（默认是当前选中的）。看照片、分析问题不需要改。
2. **先看再改**：改之前先 `lr_get_preview` 看现状和直方图数字；**小步**修改，每次改完用 `lr_get_preview`（或 `lr_set_develop` 的 `preview: true`）看效果，再决定下一步。系统有单次限幅，一次改太多会被拒绝，不要试图绕过，分几次改就是。
3. **用大白话告诉用户**每一步改了什么、为什么、预期会看到什么变化；用户可能是调色新手。引用返回的数字作依据，别只报参数。
4. **用户不满意就还原**：`lr_restore`（撤销某一次）或 `lr_restore_original`（回到最初）。还原前如果用户期间手动改过同一个滑块，要提醒他会被覆盖。
5. **用户第一次在他真实的 Lightroom 目录上使用修改功能时**，请先提醒他备份目录（`.lrcat` 文件），并建议先在测试目录上试。
6. 如果工具返回"只读模式已开启"，说明用户创建了开关文件 `C:\Users\<用户名>\LrMcp\readonly`：**不要**去删它或想办法绕过，告诉用户想允许修改就自己删掉这个文件。
7. 只改工具说明里列出的滑块。不要声称你能改白平衡、曲线、蒙版、裁剪、预设；不要用别的办法（比如操作界面）去做这些。

## 5. 对用户要讲清楚的几件事

1. **隐私**：预览图和照片信息会发给用户正在使用的 AI 服务（你所在的这个）。这个项目本身不上传任何东西，但用户应只对愿意分享的照片使用。
2. **修改是受保护的**：只能改一小批滑块，有范围和单次限幅，**写入前先把旧值存盘**，随时可以还原；用户可以创建文件 `C:\Users\<用户名>\LrMcp\readonly` 一键关掉所有修改。它在 `C:\Users\<用户名>\LrMcp` 里还会生成预览图、口令、日志和修改记录，预览图不会加入 Lightroom 目录。**真实作品请先备份目录。**
3. **可以同时开多个 AI 会话**（例如 Claude 和 Codex 各一个）：每个会话的服务各占一个端口（58770–58789），插件会自动连上所有服务；同时发来的命令在 Lightroom 里排队逐个执行。`lr_status` 会显示另有几个会话。
4. 这是个人项目，**不是 Adobe 官方产品**，早期版本，只在 Windows 11 + Lightroom Classic 15.2 上测过。

## 6. 出问题怎么办

先调用 `lr_doctor`，它逐项检查并给出处理办法。常见情况：

| 现象 | 处理 |
|---|---|
| `lr_status` 说没连上 / 插件没连上 | ① Lightroom 是否已打开；② *文件 → 增效工具管理器* 里 LrMCP 是否已启用，必要时点"重新载入增效工具"；③ 插件是否真的装在 `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`（见上面 MSIX 的提醒：必须由用户自己运行复制命令） |
| 提示端口范围 58770–58789 都被占满 | 同时开了超过 20 个服务。关掉不用的 AI 会话 |
| 工具列表里没有 `lr_*` | 客户端没登记成功或没重启。检查登记（`claude mcp get lightroom_mcp`），然后重启客户端 |
| `lr_get_preview` 很慢或超时 | Lightroom 可能在忙（导入、生成预览）。等几秒重试 |
| "没有选中的照片" | 请用户在 Lightroom 里点选一张照片 |

## 7. 卸载

`lrmcp unregister`（取消登记）→ 删除 `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`（并重启 Lightroom）→ `pip uninstall lightroom-mcp` → 可选：删除 `C:\Users\<用户名>\LrMcp`。

## 8. 把问题反馈给开发者

用户遇到问题时，请帮他整理一份反馈，**不要附照片**：

1. 调用 `lr_doctor`，把输出保存下来。
2. 记下：Windows 版本、Lightroom 版本、你所在的 AI 应用和版本、哪一步出错、出错信息。
3. 如果用户有 GitHub 账号：打开 <https://github.com/Denvolatos/lightroom-mcp-win/issues/new/choose>，选"问题反馈"，把上面的内容填进去。
4. 如果用户没有 GitHub 账号：把整理好的文字交给用户，让他直接发给把这个项目推荐给他的人。

反馈里请去掉用户不想公开的信息（比如用户名、私人路径）。

## 9. 给想改代码的 AI

见 [`AGENTS.md`](AGENTS.md)。
