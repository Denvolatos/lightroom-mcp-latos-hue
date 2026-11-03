# macOS 验证记录

> 状态：**第二阶段完成（已用真实 Lightroom Classic for Mac 验收）**。记录时间：2026-11-03（意大利时间）。
> 没有实测的项一律写"待验证"。

## 1. 环境

| 项 | 结果 |
|---|---|
| macOS | 27.0.1（Build 26A434），arm64 |
| Lightroom Classic | **15.5.1**（Windows 上测的是 15.2，版本不同，下面的差异可能来自版本而非系统，**无法区分**） |
| Python | 3.12（conda-forge 环境 `lrmcp`）；mcp 2.3.0；lupa 2.8（用 `lupa.lua51`） |
| 测试目录 | `~/ceshi/ceshil/ceshil.lrcat`，6 张照片（Sony ARW ×3、JPEG ×3，来自相机卡的副本） |
| 插件日志位置 | `~/Library/Logs/Adobe/Lightroom/LrClassicLogs/LrMcp.log`（已确认） |
| Lightroom 进程 | `/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app/Contents/MacOS/Adobe Lightroom Classic`（已确认，`lr_doctor` 的识别字符串正确） |
| `claude` 命令行 | Mac 终端里**没有**；Claude 桌面版自带的 `claude` 是 Linux 虚拟机用的，在 Mac 上无法执行 |

## 2. 单元测试

- 改之前：22 failed, 129 passed。改之后：**157 passed, 0 failed, 0 skipped**（Windows 基线 151 个）。
- 22 个失败来自两个真实的 Mac 问题（都已修）：
  1. `allow_reuse_address = False`：关闭服务后马上在同一端口重开会失败（macOS 需要 `SO_REUSEADDR` 才能重绑 `TIME_WAIT` 端口）。
  2. 插件 `Json.lua` 的 `%c` 依赖 locale：在 UTF-8 locale 下它也匹配 0x80–0x9F 字节，把中文的中间字节转成 `\u00xx`，输出变成非法 UTF-8。

## 3. 代码改动（Windows 行为不变）

| 文件 | 改动 | Windows 影响 |
|---|---|---|
| `Json.lua`、`Commands.lua`（控制字符检查） | `%c` → 显式 `[%z\1-\31\127]` | 无：等价于 Windows C locale 下 `%c` |
| `bridge.py` | `allow_reuse_address = os.name != "nt"`；非 Windows 时登记/口令文件 `chmod 600` | 无 |
| `doctor.py` | macOS 用 `ps -axo comm=` 找 Lightroom 进程；提示文字按平台显示 | 无 |
| `Commands.lua` `apply_preset` | **仅 `MAC_ENV`**：`applyDevelopPreset` 之后若照片仍与预设不同，改用 `applyDevelopSettings` 写入预设自带设置（不含蒙版） | 无（`MAC_ENV` 在 Windows 为 nil） |
| `Commands.lua` `restore_settings` | **仅 `MAC_ENV` 且要还原 `ConvertToGrayscale` 时**：缺失的颜色项分第二步写回 | 无 |
| `acceptance_presets.py` | 跳过"什么都没改"的预设；也从搜索词里找预设；新增黑白预设的整张还原检查 | 测试脚本，Windows 上同样适用（需 Windows 会话重跑确认） |
| `server/dev_tools.sh`、`devscripts/select_raw.lua`、`select_mixed3.lua` | 新增：bash 版开发通道辅助，自动选测试照片（只改选中状态，且只在路径含 `ceshi` 的目录里） | 无 |
| `devscripts/probe_preset_apply.lua` | 新增：预设套用实验脚本（只用测试目录，实验后写回） | 无 |

## 4. Mac 上发现的差异（与 Windows 15.2 对照）

1. **`photo:applyDevelopPreset` 在 15.5.1 for Mac 上返回 "executed" 但什么都不改。** 实测：121 个不带蒙版的预设全部"0 项设置改变"、预览不变；一个参数或两个参数的写法结果相同。预设本身可读（PB01 的 `ConvertToGrayscale` 为 true）。**用 `applyDevelopSettings` 写入预设自带设置有效。** 无法区分是 Mac 特有还是 15.5.x 版本特有 → 待 Windows 会话用 15.2 确认 Windows 上预设是否仍有效，以及在 Windows 上装 15.5 后是否也失效。
2. **黑白照片的设置表里没有颜色项**（HSL 色相/明亮度等），所以还原时"当前没有这个设置"。是否 Windows 上也这样 → 待验证。已用两步写入解决（Mac 分支）。
3. **没编辑过的 RAW 读不到 Temperature/Tint**，写入过一次后才出现（与 Windows 笔记中"待验证"的一项一致）。表现：第一次跑写入验收时，对白平衡的测试假设 RAW 已有色温而失败；第一次跑批量验收时，从没编辑过的 `DSC00062.ARW` 没被列入白平衡计划。重跑即通过。
4. 第一次编辑一张从没动过的 RAW 后，预览文件大小有约 0.03% 的变化（178219 → 178158 字节），之后稳定；预览文件的字节每次导出都不同（大小稳定）。与 Windows 笔记中的类似现象一致。
5. 一次偶发：`get_preview` 报"Lightroom 没有生成预览文件"，重跑未再出现 → **原因待查**。
6. Lightroom 在 Mac 上写入被卡住过一次：我的探针脚本里把 `withWriteAccessDo` 包在 `pcall` 里并出错后，Lightroom 持续拒绝所有写入（"不能写入，可能正忙"），重新载入插件无效，**完全退出 Lightroom 再打开**才恢复。结论：开发脚本里不要用 `pcall` 包 `withWriteAccessDo`。
7. `~/LrMcp/previews` 里的预览文件会不断累积（验收后 78 个），Windows 上是否有清理 → 待查。

## 5. 「要在 Mac 上实测的事」逐项结果

| # | 项目 | 结果 |
|---|---|---|
| 1 | 插件载入、`connected: true` | **已验证**（插件 0.12.0，Lightroom 15.5.1） |
| 2 | `lrmcp register` 登记 | **未验证**：Mac 终端无 `claude`；`--dry-run` 只给出 Claude 桌面版手动配置的命令 |
| 3 | 端口独占 | **已验证**：开启 `SO_REUSEADDR` 后第二个服务仍绑不上同一端口（单元测试） |
| 4 | 文件权限 | **已验证**：`~/LrMcp/servers/*.txt` 和 `token` 都是 0600 |
| 5 | `lr_get_preview` | **已验证**（0.5～0.6 秒，1024px） |
| 6 | 色温/白平衡 | **已验证**（RAW 写入验收含白平衡；见差异 3） |
| 7 | 多会话 | **已验证**：两个服务取到 58770、58771，同时连上，20 次并发调用成功。旧脚本 `acceptance_multi.py` 里有 "plug-in 0.3.x" 的版本断言已过时，未用它 |
| 8 | 更新提醒能访问 GitHub | **已验证**：`fetch_latest_tag()` 返回 v0.12.0 |
| — | Claude 桌面版 MCP 子进程是否能写 `~/LrMcp` | **待验证**（Mac 上未登记到 Claude 桌面版） |
| — | 插件安装位置（`~/Library/Application Support/Adobe/Lightroom/Modules`） | **待验证**：本次是在插件管理器里直接添加仓库里的 `plugin/lrmcp.lrdevplugin` |

## 6. 真实验收（测试目录，Lightroom 15.5.1）

| 套 | 照片 | 结果 |
|---|---|---|
| `acceptance.py`（读取） | 1 张 JPEG | **16/16 ALL PASSED** |
| `acceptance_write.py` | RAW | **40～41 项 ALL PASSED**（第一次因差异 3 失败，第二次因差异 4 的 61 字节失败，第三次起稳定通过） |
| `acceptance_write.py` | JPEG | **37 项 ALL PASSED** |
| `acceptance_metadata.py` | RAW | **9 项 ALL PASSED** |
| `acceptance_presets.py` | RAW | **16 项 ALL PASSED**（需要上面的 Mac 补救；含黑白预设整张还原；偶发一次预览导出失败，见差异 5） |
| `acceptance_batch.py` | 3 张（2 RAW + 1 JPEG） | **13 项 ALL PASSED**（第一次因差异 3 失败） |
| `acceptance_review.py` | 3 张 | **12 项 ALL PASSED** |

## 7. 剩下的 / 需要 Windows 会话或用户

1. Windows 会话核对本分支 diff，**用 15.2 重跑 Windows 验收**，特别是 `acceptance_presets.py`（改了脚本）。
2. 确认预设问题到底是 Mac 特有还是 15.5.x 特有（见差异 1）。
3. Mac 上登记到 Claude Code / Claude 桌面版：需要 Mac 版 `claude` 命令行，或手动在 *设置 → 开发者 → 编辑配置* 添加 `…/envs/lrmcp/bin/python3.12 -m lightroom_mcp`，**未测**。
4. Mac 安装包（签名、公证）不在本次范围。
5. 偶发的预览导出失败、预览目录累积，待查。
