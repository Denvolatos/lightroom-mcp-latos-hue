# 修图助手 · 对话框接入 Claude Code 命令行（只读阶段）开发记录

分支：`app`。本阶段只让对话框能"看"（Lightroom 状态/参数/预览/元数据），**不改照片**。

## 做了什么
- `app/claude_bridge.py`：拼"干净"的 `claude -p` 命令、解析 stream-json、中文错误提示、`ClaudeSession`（多轮 `--resume`、停止、180 秒超时）。
- `app/main.py`：`Api.send/stop/reset`，后台线程调用，事件经 `window.evaluate_js` 推到页面 `onClaudeEvent(obj)`。内部状态用下划线开头（pywebview 会扫描公开属性）。
- `app/web/index.html`：有 `window.pywebview.api` 就走真通道（流式文字、"正在查看照片…"小字、每轮灰字用量、发送中禁用、"停止"按钮）；否则保持原假演示，`#demo` 不变。右侧"本轮改了什么"表格未接。
- `app/tests/`：13 个 pytest（命令参数、只读白名单与服务端标注一致、解析、错误提示、找不到 claude、超时）+ `live_check.py`（真实调用脚本，不属于 pytest）。

## 干净启动配置（实测）
参数：`--strict-mcp-config --mcp-config <仅含 lightroom_mcp>`、`--setting-sources ""`（空串可用）、`--disable-slash-commands`、`--tools ""`、`--system-prompt`（短中文）、`--allowedTools`（只读）、`--disallowedTools`（写入类 10 个）、`--permission-mode dontAsk`、`--output-format stream-json --verbose --include-partial-messages`、`--resume`。工作目录 `C:\Users\DENVOLATOS\LrMcp\app_workdir`（空）。未用 `--bare`。

## 省了多少（同一句"回复两个字：收到"，实测 `claude` 2.1.317）
| 配置 | 输入侧 token（输入+缓存写+缓存读） | 客户端估算费用 |
|---|---|---|
| 默认（全局 CLAUDE.md、60 技能、18 代理、全部 MCP、全部内置工具） | 约 50,300（缓存写 23,103 + 缓存读 27,213） | $0.191 |
| 干净但只用 allowedTools（写入类工具仍在清单里） | 约 9,900（缓存写 9,905） | $0.040 |
| 干净 + `--disallowedTools` 隐藏写入类（最终采用） | 约 4,360（缓存写 4,362） | $0.0175 |

结论：约 **缩小到 1/11，费用约 1/11**。关键发现：`--allowedTools` 只放行，不会把其他工具从模型清单里去掉；加 `--disallowedTools` 才真正隐藏，又省约 5,500 token，也更安全。
真实多轮对话（含一次工具调用，Lightroom 未连上）：第 1 轮约 9,171 token / $0.0106，第 2 轮 4,855 / $0.0123（`--resume` 有效，模型记得上一句）。费用是客户端估算值，订阅账户不是实际账单。

## 实测结果
- 工具调用事件能解析（`tool:lr_status`），用量/费用能拿到，`--resume` 多轮有效。
- Lightroom 当时没连上，工具返回了排查提示，通道已通。
- 真实 `claude -p` 共调用 5 次（基线 1、干净 2、对话 2）。未打开 GUI 窗口；界面接线用无头 Edge + 假 `pywebview.api` 自查通过（发送禁用、流式、工具提示、用量行）。

## 遇到的问题
- 命令行版本实为 2.1.317（任务描述写 2.1.251）。
- `build/dist/lrmcp/lrmcp.exe`（用户 Claude 配置里用的就是它）只暴露 8 个只读工具：缺 `lr_review_selected / lr_plan_from_edit / lr_list_versions / lr_compare`。源码里有，说明 exe 是旧构建（回复里还提示有 0.13.0 新版，当前 0.11.1）。白名单写全了，缺的工具无害；待重新打包或改用源码（需 `lrmcp` 环境安装 `server/`，目前 `lrmcp` 环境里没装 `lightroom_mcp`，`claude_bridge` 在没有 exe 时会回退 `python -m lightroom_mcp` + `PYTHONPATH`，待验证）。
- Windows 控制台 GBK 乱码只是打印问题，文件和界面是 UTF-8。

## 尚未解决 / 待验证
- `CLAUDE_CONFIG_DIR` 指向空目录：未测（可能丢登录），因为已降到 ~4.4k，没必要冒险。
- 真窗口里 `evaluate_js` 回调、Api 线程行为：按 pywebview 文档编写，**未开窗口实测**，待用户方便时试。
- 回退到源码启动服务的路径未实测。
- 剩余 ~4.4k 来自系统提示 + 8~12 个工具的说明 + 服务端 instructions，再省需要精简服务端描述（改 server/，本任务未动）。
- `claude` 命令找不到/未登录的提示由单元测试覆盖，未真实触发。

## 建议下一步
1. 重新打包 lrmcp.exe（拿到完整只读工具）；2. 用户开窗口试一轮；3. 再做"写入"阶段：把 `lr_set_develop` 等从 `WRITE_TOOLS` 挪到白名单，并接右侧改动表格与"逐步询问"开关（可用 `--permission-prompt-tool` 或自己拦截）。
