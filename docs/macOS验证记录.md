# macOS 验证记录

> 状态：**第一阶段（只做代码，无 Lightroom）**。记录时间：2026-11-03（意大利时间）。
> 凡是需要真实 Lightroom Classic for Mac 的项目一律写"待验证"，没有实测的不写成已完成。

## 1. 环境

| 项 | 结果 |
|---|---|
| macOS | 27.0.1（Build 26A434） |
| 芯片 | arm64 |
| Python | 3.12（conda-forge 环境 `lrmcp`；系统 Python 是 3.14.8，未使用） |
| lupa | 2.8（测试用 `lupa.lua51`，即 Lua 5.1，与 Lightroom 一致） |
| mcp | 2.3.0 |
| Lightroom Classic | **Mac 上没有安装**（`/Applications` 里没找到）→ 所有需要它的项均为待验证 |
| `claude` 命令行 | Mac 终端里找不到 → `lrmcp register` 无法实测 |

## 2. 测试基线（改代码之前）

`python -m pytest -q`（`server/` 下）：**22 failed, 129 passed, 0 skipped**。

| 失败 | 数量 | 原因（已查明） |
|---|---|---|
| `test_bridge.py::test_port_can_be_reused_right_after_stop` | 1 | 服务关闭后立刻在同一端口重开会失败。`bridge.py` 的 `allow_reuse_address = False` 在 Windows 没问题，但 macOS 要求设 `SO_REUSEADDR` 才能重新绑定仍处于 `TIME_WAIT` 的端口。**这是真实的 Mac 问题**：用户重启 AI 会话后服务可能起不来 |
| `test_commands_lua.py` | 21 | `Json.lua` 的 `quote()` 用了 Lua 模式 `%c`（控制字符）。`%c` 依赖 C 语言的 locale：Windows 的 C locale 里只匹配 0–31 和 127，而 macOS 的 UTF-8 locale 下它还匹配 0x80–0x9F 字节，而这些字节正是汉字等多字节 UTF-8 字符的中间字节，被错误地转成 `\u00xx`，输出变成非法 UTF-8。证据：Lua 返回的原始字节里出现 `\xe4\xb8\u008d`。**若 Mac 版 Lightroom 的 Lua 也受 locale 影响（待验证），所有含中文的回复都会损坏** |

## 3. 代码改动（Windows 行为不变）

| 文件 | 改动 | Windows 影响 |
|---|---|---|
| `plugin/.../Json.lua` | `[%c"\\]` → `[%z\1-\31\127"\\]` | 无：等价于 Windows C locale 下 `%c` 的集合 |
| `plugin/.../Commands.lua` | `hasControlChars` 同上 | 同上 |
| `server/.../bridge.py` | `allow_reuse_address = os.name != "nt"` | 无：Windows 仍为 False，且仍用 `SO_EXCLUSIVEADDRUSE` |
| `server/.../bridge.py` | `restrict_to_current_user`：非 Windows 时 `chmod 600`；Windows 的 `icacls` 逻辑原样 | 无 |
| `server/.../doctor.py` | macOS 用 `ps -axo comm=` 查可执行路径是否含 `/Adobe Lightroom Classic.app/Contents/MacOS/`；提示文字按平台显示 | 无：Windows 仍用 `tasklist` |

新增测试 6 个（`test_doctor.py` 4 个、`test_bridge.py` 2 个），**改后：157 passed, 0 failed, 0 skipped**。

## 4. 第 4 节"要在 Mac 上实测的事"逐项状态

| # | 项目 | 状态 |
|---|---|---|
| 1 | 插件能否被 Lightroom 载入、`lr_status` 显示 connected | **待验证**（无 Lightroom） |
| 2 | `lrmcp register` 登记进 Claude Code | **待验证**（Mac 终端里没有 `claude`；`--dry-run` 也未跑） |
| 3 | 端口独占 | **已实测**：开启 `SO_REUSEADDR` 后，第二个服务绑定同一端口仍被拒绝（`test_second_server_cannot_listen_on_a_port_that_is_in_use`），所以"一端口一服务"在 macOS 成立。仅指同一地址 127.0.0.1；与其他程序用通配地址的冲突未测 |
| 4 | 口令/登记文件权限 | **已实测**（单元测试）：登记文件为 0600。实际 `~/LrMcp/token` 仅在占用 58770 端口时才写，测试里没覆盖到真实目录 |
| 5 | `lr_get_preview` 导出预览 | **待验证** |
| 6 | 色温/白平衡等读写差异 | **待验证** |
| 7 | 多会话端口分配 | **待验证**（端口选择逻辑在单元测试里通过，但没有真实插件轮询） |
| 8 | 更新提醒能否访问 GitHub | **待验证** |
| — | Lightroom 进程名 `Adobe Lightroom Classic` | **待验证**：是按 Adobe 常见的 .app 命名推测的，没有看过真实进程，`lr_doctor` 在 Mac 上"是否在运行"这一项可能误报 |
| — | 插件安装位置、插件日志位置 | **待验证** |
| — | Claude 桌面版的 MCP 子进程写 `~/LrMcp` 是否真的落到磁盘 | **待验证** |

## 5. 真实验收（6 套脚本）

全部**未运行**：需要 Mac 上的 Lightroom Classic 和 `ceshi` 测试目录。

## 6. 下一步（需要用户）

1. 在 Mac 上装好 Lightroom Classic，告诉我版本。
2. 建测试目录（路径含 `ceshi`，至少 1 张 RAW、1 张 JPEG，批量验收要 3 张）。
3. 装好 `claude` 命令行（或确认用哪个客户端）。
4. 之后按本文件第 4、5 节逐项实测，更新本记录。
