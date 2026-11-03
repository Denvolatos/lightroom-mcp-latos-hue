# macOS 交接说明（给在 Mac 上工作的 Claude Code 会话）

> **你是谁、要做什么：** 你是在用户的 Mac 上运行的 Claude Code 会话。这个项目（LrMCP）目前只在 Windows + Lightroom Classic 15.2 上测过。
> 你的任务是**让它在 macOS 上能用，并用真实运行验证**。Windows 那边的会话（"Windows 会话"）负责核对你的改动并重跑 Windows 验收，
> 所以**你的每一条结论都要有 Mac 上的真实运行作依据，没跑过的写"待验证"**。请先读完本文件，再动手。
> 项目说明见 `AGENTS.md`、`AI_GUIDE.md`、`docs/实验记录.md`；本文件讲的是 Mac 工作特有的内容。

## 0. 铁律（先读这几条）

1. **只在分支 `macos` 上工作。** 不要动 `main`，不要打标签，不要创建 GitHub Release，不要发布安装包。合并和发布只有用户和 Windows 会话能决定。
2. **Windows 的行为一个字都不能变。** 平台相关的代码只能加在 `sys.platform == "darwin"`（或 `os.name`）判断后面的新分支里；不要重构 Windows 路径，不要改 `build.ps1`、`installer/`、`dev_tools.ps1`。
3. **所有现有测试必须继续通过。** 在 Mac 上先装 `lupa`（见 2.2），否则 Lua 插件逻辑的测试会被**静默跳过**，看起来全绿其实没跑。Windows 上基线是 `151 passed`，没有 skipped。
4. **只用测试目录和测试照片。** 真实验收脚本的保护要求目录路径里含 `ceshi`（比如 `~/ceshi/ceshi1.lrcat`），不要绕过；不要碰用户真实的照片目录。验收期间**用户不要点 Lightroom**，选中的照片一变，结果就废了。
5. **提交信息用中文，不加 `Co-Authored-By`，不同类别分开提交**（代码、测试、文档分开）。提交前 `git status` 看一眼，不要用 `git add -A` 把别的东西带进来。
6. **脚本不要用大段 heredoc**，也不要在 Python 非原始字符串里写带反斜杠的路径。用文件写脚本再运行。
7. **诚实：** 没实测的写"待验证"；失败了就如实写失败和原因，不要为了好看改测试。
8. 时间一律用意大利时间：`TZ=Europe/Rome date`。

## 1. 先摸清环境（把结果写进 `docs/macOS验证记录.md`）

```bash
sw_vers                      # macOS 版本、芯片
uname -m                     # arm64 还是 x86_64
python3 --version            # 需要 3.10 或更新
git --version
claude --version             # Claude Code 命令行（用来登记 MCP 服务）
```

让用户在 Lightroom 里看 *帮助 → 系统信息*，告诉你 **Lightroom Classic 的版本**（Windows 上测的是 15.2）。
如果 Mac 上没有 Lightroom Classic，**停下来告诉用户**，没有它什么都验证不了。

## 2. 装好开发环境并跑基线

```bash
git clone https://github.com/Denvolatos/lightroom-mcp-win.git ~/lightroom-mcp-win   # 已有就 git fetch
cd ~/lightroom-mcp-win && git checkout macos
python3 -m venv ~/.venvs/lrmcp && source ~/.venvs/lrmcp/bin/activate
pip install -e "./server[test]" lupa
cd server && python -m pytest -q          # 记下通过/失败/跳过的数量
```

**在改任何代码之前**，把基线结果原样记下来：哪些测试在 Mac 上失败了、为什么。很可能失败的是测 Windows 专用行为的测试
（`test_doctor.py` 里模拟 `tasklist`，`test_bridge.py` / `test_servers.py` 里关于"独占端口"的）。
这些失败**不要靠删测试或放宽断言来消除**：要么给测试加平台条件（`pytest.mark.skipif(sys.platform != "win32", ...)`）并另写 Mac 版的测试，要么修代码。

## 3. 已知的 Windows 专用位置（先看过代码再动）

| 位置 | 现状 | Mac 上要做什么 |
|---|---|---|
| `server/lightroom_mcp/doctor.py`（`_lightroom_running` 附近） | 用 `tasklist` 找 `Lightroom.exe` | 加 macOS 分支：检查进程名含 `Adobe Lightroom Classic`（用 `pgrep -f` 或 `ps`；先在 Mac 上看真实进程名），并把提示里的 "Lightroom.exe" 说法改成按平台显示 |
| `server/lightroom_mcp/bridge.py` `restrict_to_current_user` | 只有 `os.name == "nt"` 时用 `icacls`；其他平台**直接跳过** | macOS 加 `os.chmod(path, 0o600)`（口令/登记文件只有当前用户可读写），并补测试 |
| `server/lightroom_mcp/bridge.py` 端口独占 | Windows 用 `SO_EXCLUSIVEADDRUSE`，因为 Windows 的 `SO_REUSEADDR` 允许两个进程共用端口 | **先实测**：在 Mac 上用 Python 起两个服务绑同一个端口，看第二个是否失败。`socketserver` 默认设 `SO_REUSEADDR`，macOS 上通常仍不允许两个监听同一地址，但不要凭记忆，写一个测试证明 |
| `server/lightroom_mcp/config.py` | 数据目录 `~/LrMcp`；注释里讲的是 Windows 商店版 Claude 桌面版（MSIX）会重定向 AppData | Mac 上应该没有这个问题，但**要验证**：如果用户用 Claude 桌面版，让它的 MCP 子进程在 `~/LrMcp` 写一个文件，再用终端看这个文件是否真的在 |
| 插件 `Bridge.lua` / `Commands.lua` | 路径全部走 `LrPathUtils.getStandardFilePath("home")`，没有写死反斜杠 | 理论上不用改。**验证**插件在 Mac 上能读到 `~/LrMcp/servers/*.txt`，预览能导出到 `~/LrMcp/previews` |
| 插件安装位置 | Windows：`%APPDATA%\Adobe\Lightroom\Modules\LrMcp.lrplugin` | Mac 上很可能是 `~/Library/Application Support/Adobe/Lightroom/Modules/LrMcp.lrplugin`（**待验证**，以 Lightroom 实际为准）。开发时也可以在插件管理器里用 *添加* 直接指向仓库里的 `plugin/lrmcp.lrdevplugin` |
| 插件日志 | Windows 没找到日志文件（待查） | 在 Mac 上找 `LrMcp.log`（通常在 `~/Library/Logs/Adobe/Lightroom/LrClassicLogs/`，待验证），记下位置 |
| `AI_GUIDE.md` 第 3 节 | 全是 PowerShell 命令和 Windows 路径 | 增加 Mac 小节（bash 命令、Mac 路径），保留 Windows 内容不动 |
| `README.md` / `README.en.md` | 写的是 Windows | 加"macOS（实验，待验证）"说明，**不要写成已支持**，直到真实验收通过 |
| 开发辅助脚本 | `server/dev_tools.ps1` 是 PowerShell，用来通过"开发通道"自动选照片、跑 Lua 脚本 | 先不用移植；验收时让用户手动选照片即可。需要的话可以写 bash 版，但不是必须 |
| 打包 | `build.ps1`、`installer/lrmcp.iss`（PyInstaller + Inno Setup）只适用 Windows | **这次不做 Mac 安装包。** 先用 `pip install` 的方式装服务；安装包要不要做、要不要付费签名公证，等验证通过后由用户决定 |

## 4. 要在 Mac 上实测并记录的事（每一项都写：做了什么、看到什么、结论）

1. 插件能否被 Lightroom 载入（插件管理器里是绿点？）。载入后 `~/LrMcp/servers/` 有没有被插件读到（`lr_status` 里 `connected: true`）。
2. `lrmcp register` 能否把服务登记进 Claude Code（`claude mcp get lightroom_mcp`）；重启 Claude Code 后工具列表里有没有 `lr_*`。
3. 端口独占（见上表）。
4. 口令文件权限：`ls -l ~/LrMcp/servers/ ~/LrMcp/token` 应该只有当前用户可读写。
5. `lr_get_preview` 能否导出预览并返回图片（Lightroom 导出到 `~/LrMcp/previews`）。
6. Lightroom 在 Mac 上读写相关的差异：色温读取、`Temperature/Tint` 对 RAW/JPEG 的表现、`gray` 标签等，与 Windows 的实验记录对照，发现不同就记下。
7. 多个 AI 会话同时连（开两个 Claude Code）时端口分配是否正常。
8. 更新提醒（`lr_status` 里的 `update_available`）在 Mac 上能访问 GitHub 吗（证书/代理问题）。

## 5. 真实验收（在测试目录里，用户不要点 Lightroom）

```bash
cd ~/lightroom-mcp-win && source ~/.venvs/lrmcp/bin/activate
python server/tests/acceptance.py             # 读取：选中 1 张照片
python server/tests/acceptance_write.py       # 写入与还原：选中 1 张 RAW，目录路径含 ceshi
python server/tests/acceptance_metadata.py    # 目录信息：选中 1 张
python server/tests/acceptance_presets.py     # 预设：选中 1 张**没有蒙版**的 RAW
python server/tests/acceptance_batch.py       # 批量：选中 3 张（含 RAW 和 JPEG）
python server/tests/acceptance_review.py      # 多图挑片、前后对比、还原冲突保护：选中 3 张
```

- 每套脚本末尾应该是 `ALL PASSED`；输出里有 `FAIL` 或 `Traceback` 就是没通过，不要隐瞒。
- 这些脚本运行时会改测试照片并在结束时还原，最后一项是"整张设置回到开始"。
- 如果终端编码不是 UTF-8，加 `PYTHONIOENCODING=utf-8`。
- 一套没通过，先查是不是选照片的问题（数量、有没有蒙版、选中的照片被换了），再怀疑代码。

## 6. 交付物（都在分支 `macos` 上）

1. 代码：Mac 分支的服务端修改 + 测试，Windows 行为不变，`pytest` 全过（Mac 上数量写进记录）。
2. `docs/macOS验证记录.md`：环境、基线结果、第 4 节每一项的实测、第 5 节每套验收的结果，**没验证的项明确写"待验证"**。
3. `AI_GUIDE.md` 的 Mac 小节、README 的"macOS（实验）"说明、`CHANGELOG.md` 的 Unreleased 条目。
4. 一份给用户的总结：Mac 上现在能做什么、不能做什么、剩下什么。

做完后**推送 `macos` 分支**并告诉用户。不要合并到 `main`。Windows 会话会核对 diff、重跑 Windows 的真实验收，用户确认后才合并。

## 7. 需要用户亲手做的事（你没法替他点）

- 确认 Mac 上装了 Lightroom Classic，告诉你版本。
- 打开一个**测试目录**（路径含 `ceshi`）并放几张测试照片（至少 1 张 RAW、1 张 JPEG，批量验收要 3 张）。
- 在 Lightroom *文件 → 增效工具管理器* 里添加/重新载入插件；改了插件代码后要重新载入。
- 每套验收开始前选中正确数量的照片，验收期间不要点 Lightroom。

## 8. 已知的坑（Windows 上踩过的）

- Lua 逻辑测试需要 `lupa`，没装会静默跳过（见 0.3）。
- Lightroom 会把"没有颜色标签"报告成 `gray`，插件已统一显示为 `none`。
- 当前选中的照片读不到蒙版，通过 SDK 写蒙版不可靠（实验 11），所以项目不做蒙版；预设验收要选没有蒙版的照片。
- Lightroom 会自己生成 `GrainSeed`、`DepthMapInfo` 等内部键，还原不掉，验收脚本已把"开始时不存在的键"排除在比较之外。
- 发布命令要失败即停，这条对你不适用（你不发布），但如果要跑 `pytest`/脚本，也别用 `;` 串联后忽略失败。
