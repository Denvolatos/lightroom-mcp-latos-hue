# 📸 Lightroom MCP（Windows）

**让 Claude / Codex 帮你看 Adobe Lightroom Classic 里的照片。**
一个 Lightroom 插件加一个小型 MCP 服务：能看到你选中的照片、读取调整参数，并把预览图和直方图数字交给 AI。
**目前只读，不会修改你的照片。**

![License: MIT](https://img.shields.io/badge/license-MIT-blue) ![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey) ![Status: early](https://img.shields.io/badge/status-early%200.1.0-orange)

[English](README.md) · [更新日志](CHANGELOG.md) · [安全说明](SECURITY.md) · [参与贡献](CONTRIBUTING.md)

> ⚠️ **早期版本（0.1.0）**：只在 Windows 11 + Lightroom Classic 15.2 上测过，暂未发布安装包。与 Adobe 无关联。

## ✨ 能做什么

| 工具 | 给 AI 的内容 |
|---|---|
| `lr_status` | Lightroom 是否连上、版本、当前目录、选中几张 |
| `lr_list_selected` | 选中的照片：文件名、格式、评分、尺寸、ISO/光圈/快门/焦距/镜头/机身 |
| `lr_get_develop` | 当前调整参数：曝光、对比度、高光、阴影、白平衡、HSL 等 |
| `lr_get_preview` | 1024 像素预览（可选 256–2048）**加数字**：亮度、过曝/欠曝比例、冷暖偏向 |
| `lr_doctor` | 中文自检：哪里有问题、怎么处理 |

例子：选中一张照片，对 AI 说「看看我选中的这张，曝光有什么问题」。它拿到图片和 `平均亮度 77.6`、`冷暖指数 −9.9%`
这样的数字，就能有依据地说「偏暗、偏冷」。

它**不会写入你的照片**：只会在 `C:\Users\<你>\LrMcp` 里生成预览图、口令和日志（预览图不会加入你的 Lightroom 目录）。

## 🏗️ 结构

```
Claude / Codex ──(MCP, stdio)──▶ lrmcp（Python 服务，本机队列 127.0.0.1:58770）
                                          ▲
        Lightroom 插件（Lua）来取任务，执行白名单命令，再把结果送回
```

- 只在本机：服务独占绑定 `127.0.0.1`，请求要带随机口令，`Host` 必须匹配，带 `Origin` 头（浏览器）的请求一律拒绝；同一时间只支持一个服务实例。
- 插件只执行固定的白名单命令，不接受请求里的文件路径。
- 注意：工具返回的图片和照片信息会发给你使用的 AI 服务，见 [SECURITY.md](SECURITY.md)。

## 🧰 需要什么

- Windows、Adobe Lightroom Classic（在 15.2 上开发；SDK 15.x）、Python 3.10+（用 3.12 测试）。
- Claude Code、Codex 或其他 MCP 客户端（测试过 Claude Code，没测过 Codex）。

## 🚀 从源码安装

1. **服务**（普通 PowerShell）：
   ```powershell
   pip install ./server
   lrmcp register --dry-run   # 先看它会做什么
   lrmcp register             # 把 lightroom_mcp 登记到 Claude Code / Codex（调用它们自己的命令）
   ```
2. **插件**：把 `plugin/lrmcp.lrdevplugin` 复制到 `%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin`，
   删掉副本里的 `DevRun.lua` 和 `devscripts` 文件夹（开发用的辅助），重启 Lightroom。在
   *文件 → 增效工具管理器* 里应能看到 LrMCP 已启用。`powershell -ExecutionPolicy Bypass -File build.ps1`
   可以生成干净的插件副本和安装包（需要 conda 环境和 Inno Setup，见 [CONTRIBUTING](CONTRIBUTING.md)）。
3. 重启你的 AI 助手，让它调用 `lr_status`。出问题就让它调用 `lr_doctor`。

> **Windows 的坑**：*Claude 桌面版是 MSIX 应用*，Windows 会悄悄重定向它启动的程序对 `AppData` 的写入。
> 请在你自己的 PowerShell 里运行安装和复制步骤，不要通过 Claude 桌面版启动的 shell。
> 所以本项目的共享文件放在 `C:\Users\<你>\LrMcp`，而不是 `AppData`。

Claude 桌面版暂不自动登记（配置文件位置取决于安装方式），请在 *设置 → 开发者 → 编辑配置* 里手动添加命令。

## 🗺️ 路线图

| 版本 | 计划 |
|---|---|
| 0.1（现在） | 只读：看照片、调整参数、预览、直方图数字、自检 |
| 下一步 | 修改单张照片的全局滑块：范围限制、改前备份与还原命令、只读开关 |
| 之后 | 教学模式（大白话解释、前后对比）、学习你的口味、批量/预设/挑片 |

蒙版、AI 功能、色调曲线取决于 Adobe SDK 能提供什么，暂不承诺。

## 📚 文档

- [`docs/方案.md`](docs/方案.md)：方案与设计
- [`docs/实验记录.md`](docs/实验记录.md)：在 Lightroom Classic 15.2 上的实测（例如：写入必须放进 `withWriteAccessDo`，快照和撤销不可靠）
- [`docs/实现记录.md`](docs/实现记录.md)：实现中的发现与验证结果

## 🙏 另见

其他 Lightroom Classic MCP 项目，参考过思路（没有复制代码）：
[Automaat/lightroom-mcp](https://github.com/Automaat/lightroom-mcp)（TypeScript，MIT，工具很多，支持 Windows 和 macOS）、
[noopz/lightroom_mcp](https://github.com/noopz/lightroom_mcp)（Python，Apache-2.0）。
本项目的目标是：小而只读优先、用 Python、方便不懂编程的人安装。

## ⚖️ 许可证与声明

[MIT](LICENSE)。第三方依赖见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
Adobe、Lightroom 是 Adobe Inc. 的商标；本项目与 Adobe 无关联，未获其认可或赞助。
Adobe Lightroom Classic SDK 不在本仓库内，也不要提交。
