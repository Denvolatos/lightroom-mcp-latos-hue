# AI 来源接口（给贡献者）

> **English summary.** The desktop app talks to AI backends through `AIProvider` (`app/providers/base.py`). Claude and Codex CLI are implemented; API is a placeholder. Codex uses `codex exec --json`, thread resume, and a restricted MCP proxy that checks every write with the app's confirmation endpoint. The provider contract test runs without a real model. See the verification status in section 9 and attach a verification report to your PR (see `CONTRIBUTING.md`).

本文说明：如何给"修图助手"桌面软件接入一个新的 AI 来源，**不需要阅读软件的其他源码**。已实现的来源有 `claude` 和 `codex` 命令行。

## 1. 目的与整体结构

软件的界面不关心背后是哪家 AI。每个"来源"只负责三件事：收一句用户的话，把 AI 的输出翻译成统一的"事件"，并保证 AI 只能用被允许的 Lightroom 工具。

```
  界面（对话框、确认卡片、"本次调整"表、预览）
        ▲  事件（JSON）                 │ 用户消息 / 停止 / 新对话
        │                               ▼
  ┌──────────────── AIProvider（本接口）────────────────┐
  │  status  start  send  stop  reset  close            │
  └───────┬─────────────────────────────────┬───────────┘
          │ 启动并驱动                       │ 写入类工具先问软件
          ▼                                 ▼
   AI 命令行 / API ──调用工具──► lightroom_mcp（MCP 服务，由 Lightroom 插件执行）
                         ▲
                         └── 逐项确认：来源 → 软件的确认端点（见第 5 节）→ 界面卡片 → 用户点"同意/拒绝"
```

相关文件（仓库内，`app` 分支）：

| 文件 | 内容 |
|---|---|
| `app/providers/base.py` | `AIProvider` 抽象类、事件字段表 `EVENT_FIELDS`、`validate_event()`、`make_status()` |
| `app/providers/__init__.py` | 注册表 `available_providers()`、`create_provider()` |
| `app/providers/claude_provider.py` | 已实现的参考来源（对 Claude 命令行常驻会话的封装） |
| `app/providers/codex_provider.py` | Codex CLI 的 JSONL、续聊、中断与状态适配 |
| `app/codex_proxy.py` | 仅暴露允许的 Lightroom 工具，写入前强制询问确认端点 |
| `app/tests/test_provider_contract.py` | 契约测试，可直接复用 |
| `app/tests/test_codex_safety.py`、`app/tests/test_codex_integration.py` | Codex 的安全边界（代理、确认）与集成核对（挑片期间拒绝写入、"逐项确认"开关、来源切换、环境变量传递） |

## 2. 事件格式

`send(text, on_event)` 阻塞到本轮结束；其间每个事件调用一次 `on_event(dict)`（可在其他线程调用）。下面的字段以现有 Claude 实现实际产生的为准。

| type | 字段 | 含义 |
|---|---|---|
| `session` | `id` | 会话标识（可选，用于续接对话） |
| `text` | `text` | 回复文字的**增量片段**，界面按到达顺序拼接 |
| `tool` | `name`、`id`、`input`、`label` | 调用了某个 Lightroom 工具。`name` 不含服务前缀（如 `lr_get_develop`）；`label` 是界面小字（中文，如"正在读取调整参数"） |
| `tool_result` | `id`、`text`、`is_error` | 工具返回。`id` 对应 `tool` 事件的 `id`；`text` 是工具原文返回。"本次调整"表据此记录改前/改后 |
| `error` | `message` | 中文错误提示（用户看得懂，如"Claude 命令行尚未登录。请在终端运行 claude，输入 /login 完成登录后重试。"） |
| `stopped` | 无 | 本轮被用户中断。随后仍会有 `done` |
| `done` | `tokens`、`cost`、`text`、`is_error` | 本轮结束。`tokens` 整数（取不到填 0）；`cost` 数值或 `null`（取不到填 `null`，不得编造）；`text` 为完整回复；`is_error` 为是否失败 |

示例（一轮正常对话，每行一个事件）：

```json
{"type": "session", "id": "SESS-1"}
{"type": "text", "text": "先查看当前照片。"}
{"type": "tool", "name": "lr_get_develop", "id": "T1", "input": {}, "label": "正在读取调整参数"}
{"type": "tool_result", "id": "T1", "text": "{\"Exposure2012\": 0.0}", "is_error": false}
{"type": "text", "text": "当前曝光为 0。"}
{"type": "done", "tokens": 4362, "cost": 0.0175, "text": "先查看当前照片。当前曝光为 0。", "is_error": false}
```

出错的一轮：

```json
{"type": "error", "message": "网络连接异常，请检查网络后重试。"}
{"type": "done", "tokens": 0, "cost": null, "text": "", "is_error": true}
```

被中断的一轮：

```json
{"type": "text", "text": "开始"}
{"type": "stopped"}
{"type": "done", "tokens": 0, "cost": null, "text": "", "is_error": true}
```

**硬性规则**

1. 每次 `send()` **有且仅有一个** `done`，且它是最后一个事件。出错也先发 `error` 再发 `done`。
2. 被中断时发 `stopped` 再发 `done`；中断产生的"错误"（如进程报告请求被取消）不要当作 `error` 发出。
3. 所有 `error.message` 必须是中文、可读，不得包含口令、密钥、登录信息或本机个人路径。
4. 软件自己产生、**来源不需要发**的事件：`confirm` / `confirm_done`（确认卡片）、`status`、`photo`、`adjust`、`preview`、`connecting`。

## 3. 一个来源要实现的方法

继承 `AIProvider`，设置类属性并实现方法：

| 成员 | 说明 |
|---|---|
| `id` | 稳定的英文标识（小写字母/数字/下划线），写入设置文件，如 `codex` |
| `display_name` | 界面显示名（中文） |
| `supports_images` | 能否看图（`lr_get_preview` 返回的预览图）。不能看图的来源要在文档里说明如何降级 |
| `experimental` / `experimental_notice` / `privacy_notice` | 可选类属性（0.12.0 新增，以代码为准）。`experimental = True` 时设置下拉里标注"（实验性，未经真机验证）"并在下方显示 `experimental_notice`；`privacy_notice` 非空时在设置里显示（如照片预览会发送到哪里）。这些字段随注册表 `available_providers()` 返回 |
| `status()` | 返回 `make_status(available, state, reason, next_step)`：`available` 是否可用；`state` 取 `ready` / `not_installed` / `not_logged_in` / `unavailable` / `unknown`；`reason`、`next_step` 为中文（不可用时 `next_step` 不得为空）。**不得为检测而发起真实模型调用**，应在约 10 秒内返回；建议缓存几十秒 |
| `start(env)` | 预热（可选的优化），返回是否成功。`env` 含确认端点的端口与一次性口令（第 5 节），需原样传给子进程 |
| `send(text, on_event, **options)` | 发送一条用户消息，流式回调事件，见第 2 节 |
| `stop()` | 中断当前这一轮（可从其他线程调用）。**会话要保留**，之后还能继续 `send()` |
| `reset()` | 新对话，清空上下文 |
| `close()` | 退出软件时释放进程与连接，可重复调用 |

在 `app/providers/__init__.py` 的 `IMPLEMENTED` 里登记，并把 `PLACEHOLDERS` 里对应占位条目移除。登记后，设置里的"AI 来源"下拉框就会出现它；切换来源在下一次"新对话"生效。

## 4. 如何让来源使用 Lightroom 工具

Lightroom 工具由 `lightroom_mcp` 这个 MCP 服务提供（stdio）。启动配置用 `claude_bridge.lightroom_server_config()` 取得，返回形如：

```json
{"type": "stdio", "command": "<python 或 lrmcp.exe 的路径>", "args": ["<启动脚本>"], "env": {"PYTHONPATH": "<server 目录>"}}
```

把它放进 MCP 客户端的配置即可（Claude 用的是 `{"mcpServers": {"lightroom_mcp": <上面的配置>}}`，见 `claude_bridge.write_mcp_config()`）。Codex 使用 `codex exec -c mcp_servers.lightroom_mcp.*` 配置本轮代理服务。注意：

- 只开放白名单工具。只读：`claude_bridge.READONLY_TOOLS`；写入类**目前仅** `lr_set_develop`（调整）、`lr_restore`（撤销）、`lr_restore_original`（还原）。其余写入/导出/删除类工具（`claude_bridge.BLOCKED_WRITE_TOOLS`）一律不开放，并且最好直接从模型可见的工具清单里隐藏（实测可省约 5500 token，也更安全）。
- 系统提示词可参考 `claude_bridge.SYSTEM_PROMPT`（正式、克制的书面语气；仅在用户明确要求时修改；每项调整写明依据）。提示词只是行为引导，**不能代替安全措施**。
- 工作目录应是空的中性文件夹（`claude_bridge.WORKDIR`），避免来源读到无关的项目文件或全局配置。
- 工具名在事件里要去掉服务前缀（`mcp__lightroom_mcp__lr_status` → `lr_status`）。

## 5. 逐项确认怎么接

目标：开着"逐项确认"时，任何写入（调整/撤销/还原）**必须先经软件确认，由软件强制，而不是靠提示词**。软件侧机制是 `ConfirmHub`（`app/confirm_hub.py`），来源只需在每次写入前向它提问。

**确认端点（软件提供，仅本机）**

- 地址：`POST http://127.0.0.1:<LRAPP_PORT>/ask`，端口与口令由软件通过环境变量 `LRAPP_PORT`、`LRAPP_TOKEN` 传给来源（`start(env)` 的 `env`）。口令是一次性的，随会话/进程重建而更换，**不得写入任何文件或日志**。
- 请求头：`Authorization: Bearer <LRAPP_TOKEN>`；`Content-Type: application/json`。
- 请求体：`{"tool_name": "mcp__lightroom_mcp__lr_set_develop", "input": {...工具参数...}, "tool_use_id": "T9"}`。
- 响应：`{"allow": true|false, "message": "..."}`。请求会**阻塞**到用户点击或超时（120 秒）。
  - 同意：`allow: true`；
  - 拒绝：`allow: false`，`message` = "用户在界面中拒绝了该项调整，未执行。"；
  - 超时：`allow: false`，`message` = "确认超过 120 秒未响应，已视为拒绝，未执行。"；
  - 本轮被停止：`allow: false`，`message` = "本轮已被停止，该项调整未执行。"；
  - 口令错误/未连接：HTTP 401 或连接失败 → 一律按**拒绝**处理。
- 来源收到 `allow: false` 时**不得执行该工具**，应把 `message` 告诉模型（模型会如实向用户说明，不重复尝试）。
- "逐项确认"关闭时，软件的端点会对上述三类写入工具直接返回 `allow: true`（来源的进程参数不用变），所以来源**始终**走同一条路径即可。

**实现建议（按来源能力选择；以下为建议，均待验证）**

1. **来源命令行有"权限询问回调"机制**（Claude 的做法，已验证）：Claude 用 `--permission-prompt-tool` 指向一个小 MCP 服务（`app/permission_server.py`），该服务把请求转发到上面的端点，再按 Claude 要求的格式返回（允许时带 `updatedInput`，拒绝时带 `message`）。写入类工具不放进"自动放行"清单，于是每次写入都会触发回调。
2. **命令行没有类似机制**（Codex 是否如此：待验证）：退回"软件在转发工具调用前先询问"。做法：来源不让模型直接连 `lightroom_mcp`，而是自己启动一个**代理 MCP 服务**转发工具调用——读取类原样转发；写入类先向 `/ask` 询问，`allow` 才转发给真正的 `lightroom_mcp`，否则返回"拒绝"的工具结果。这样强制发生在代码里，不依赖模型是否听话。
3. **纯 API 来源**（模型本身不执行工具，由来源代码执行工具循环）：在来源代码执行每个写入类工具之前调用 `/ask`，这是最简单的情形。

无论哪种方式，都要有测试证明：拒绝/超时/端点不可达时，写入**确实没有执行**。

## 6. 安全要求

1. **只可使用白名单内的工具**：写入类目前仅 `lr_set_develop`、`lr_restore`、`lr_restore_original`；其余一律不开放（不是"提示模型别用"，而是配置层面不提供）。
2. **逐项确认由软件强制**：开着"逐项确认"时，任何写入必须先经 `/ask`；不可用"请模型先询问用户"代替。
3. **绝不把口令、API 密钥、登录信息写进文件或日志**（包括测试输出、`error.message`、验证报告和截图）。确认端点的口令只在内存与子进程环境变量里。
4. **不得读取或上传照片之外的用户文件**：不开放文件读写/执行类工具（Claude 实现里 `--tools ""` 关闭了全部内置工具）；工作目录用空文件夹。
5. **不得联网上传照片**：预览图只交给用户所选的那个 AI 来源，不得转发给其他服务。使用云端 API 的来源，必须在界面/文档里明确告知照片预览会发送给该服务商。
6. 状态检测不得发起真实模型调用，也不得读取账号信息以外的内容；不要保存检测到的账号信息。
7. 超时、断线、异常一律按"拒绝/失败"处理，宁可不执行也不要默认放行。

## 7. 怎么自测

**契约测试（不需要真实模型）**

```
python -m pytest app/tests/test_provider_contract.py -q
```

文件里有一个 `FakeProvider`（最小的合格实现）和 `ProviderContract`（通用测试集）。给你的来源写一个 harness 类：

```python
class TestMyProvider(ProviderContract):
    NORMAL, SLOW, ERROR = "<触发正常一轮的消息>", "<触发可被中断的长回复>", "<触发出错>"
    def make(self, tmp_path, monkeypatch):   # 返回已 start() 的来源；用假的输出源替代真实 AI
        ...
    def context_size(self, p):               # 对话上下文大小；reset 后应为 0
        ...
```

通用测试覆盖：身份信息、`status()` 返回格式、事件顺序与字段（`done` 有且仅有一个且在最后、先调用后返回、工具名无前缀）、`stop` 后会话仍可继续、`reset` 清空、错误为中文且以 `done` 收尾、`close` 可重复调用。`ClaudeProvider` 也跑同一组（用假的 claude 进程）。

**真机检查清单**（用测试目录里的测试照片，不要用真实照片目录）

- [ ] 只读：让 AI 读取当前照片的曝光值，界面出现"正在读取…"小字和文字回复，用量行正常
- [ ] 逐项确认开：提出一项小调整，弹出确认卡片；点"拒绝"→照片不变且 AI 如实说明；再试一次点"同意"→数值变化，"本次调整"表出现记录
- [ ] 逐项确认开：不点击，等待 120 秒→视为拒绝，照片不变
- [ ] 逐项确认关：调整直接执行，表中有记录
- [ ] 停止：长回复中途点"停止"→出现"已停止"，之后能继续对话
- [ ] 新对话：清空上下文，AI 不记得上一段
- [ ] 撤销 / 还原到原始状态后，数值回到起点
- [ ] 未安装/未登录时，设置里的状态与发送时的错误提示是中文且给出下一步
- [ ] 尝试让 AI 做非白名单操作（导出、删除版本等）→ 不可用
- [ ] 检查日志与输出：没有口令、密钥、个人路径

## 8. 验证报告怎么写

仓库 `CONTRIBUTING.md` 要求 PR 附"验证报告"（PR 模板里有填写项）。接入新来源时请写明：

- **环境**：操作系统、Lightroom Classic 版本、插件版本、该命令行/API 的版本；使用的是测试目录（不是真实照片库）。
- **改动范围与可能影响**：是否有写入照片的路径、读写了哪些文件、是否联网、联网发往哪里。
- **验证方法**：执行的步骤或命令，附原始输出或截图（截图不得含个人信息）。包括契约测试的结果（通过数）。
- **真机已验证**：逐条对应第 7 节清单，写明哪几条通过。
- **没验证的**：凡没有亲自验证的一律写"待验证"，不要写成"应该可以"。
- **已知限制和风险**：例如不能看图、用量取不到、中断后需要重建进程等。

维护者根据报告评估可信度；写入类功能（含确认流程）仍会被逐行审查。

## 9. Codex：验证清单

使用前需安装并登录 Codex CLI（`codex login`）。默认读取 Codex 自己的登录目录；若用户迁移过该目录，可在启动软件前设置 `LRAPP_CODEX_HOME`。软件不复制或保存登录凭据。Codex 预览图会发送给用户选择的 Codex 服务。

Codex 的 MCP 配置通过 `env_vars` 转发确认端点的环境变量名，令牌值不写入命令行或配置文件；代理启动 Lightroom 子进程前会移除这两个变量。提示词通过标准输入传入，避免 Windows 命令行长度限制。实际 Codex 子进程的环境继承和完整确认流程仍需实机验证。

以下是当前实现的验证范围；未勾选项目仍需实机验证：

- [x] `codex exec --json` 输出逐行 JSON；适配 `thread.started`、`item.*`、`turn.completed` 和失败事件
- [x] `codex exec resume <thread_id>` 续聊；假进程契约测试覆盖两轮和中断后续聊
- [x] 命令行 `-c mcp_servers.lightroom_mcp.*` 只配置本轮，并用 `--ignore-user-config`
- [x] 代理 MCP 对三种写入先询问 `/ask`；没有有效端点或明确同意时拒绝
- [x] 代理 MCP 只列出允许的 Lightroom 工具；Codex 配置关闭 shell、应用与图片查看内置工具，并使用只读沙箱
- [x] 结束本轮进程并保留 thread id；契约测试覆盖继续对话
- [ ] 能否接收 `lr_get_preview` 返回的图片（决定 `supports_images`）
- [x] `codex login status` 只做本地状态检测
- [x] `turn.completed.usage` 提供 token 计数；费用填 `null`
- [ ] 未登录、额度、网络目前合并为中文通用错误，细分原因待验证
- [ ] 使用 `CREATE_NO_WINDOW`；GUI 实机观察待验证

## 10. 软件侧如何对待来源（0.12.0，以代码为准）

- **挑片期间禁止写入与来源无关**：`ConfirmHub.deny_all` 在确认端点最先判断，AI 挑片进行中，任何来源（包括经 Codex 代理）请求 `lr_set_develop` / `lr_restore` / `lr_restore_original` 一律被拒且不弹卡片；"逐项确认"关闭（`auto_allow`）也不例外。
- **"逐项确认"开关**：由 `ConfirmHub.auto_allow` 实现，来源始终走 `/ask`，不用改进程参数。
- **每轮启动 vs 常驻**：Claude 默认常驻会话（`start(env)` 传入端口与口令，会话期间有效）；Codex 每轮启动 CLI，软件经 `send(..., confirm=, extra_env=)` 传入本轮的端口与一次性口令，轮结束作废。两种来源切换时，软件会重建 Lightroom 通道并让图库、挑片、预设/经验、导入、导出重新绑定，旧来源被 `close()`。
- **超时**：来源的单轮超时应发 `error`，`message` 取 `claude_bridge.MSG_TIMEOUT`，AI 挑片与"记成经验"据此识别超时。
- **实验性标记**：新接入、尚未真机验收的来源应设 `experimental = True`。Codex 已由贡献者 Galio1991 在 Windows + Lightroom Classic 15.0（测试目录）上验收（读取预览、确认写入与撤销、拒绝路径、环境变量传递、模型自行调用 `lr_restore`，见 PR #5/#6 的验证报告），已去掉该标记；尚未覆盖的有：命令行黑窗口只做了采样观察（不能排除短暂闪现）。第 9 节未勾选项即未验证清单。
