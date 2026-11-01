# 📸 Lightroom MCP（Windows）

让 Claude / Codex 帮你看自己拍的照片：Lightroom Classic 的 Lua 插件 + Python MCP 服务。

> 🚧 **v1.0 开发中（当前 0.1.0）**：只看不改，已在 Windows + Lightroom Classic 15.2 上通过验收测试。**非 Adobe 官方项目**，与 Adobe 无关联。

## ✨ 现在能做什么（只读）

| 工具 | 作用 |
|---|---|
| `lr_status` | Lightroom 是否连上、版本、当前目录、选中几张 |
| `lr_list_selected` | 选中的照片：文件名、格式、评分、尺寸、ISO/光圈/快门/焦距/镜头/机身 |
| `lr_get_develop` | 读当前调整参数（曝光、对比度、高光、阴影、白平衡、HSL 等） |
| `lr_get_preview` | 给 AI 看图：1024 像素预览 + 直方图数字（亮度、过曝/欠曝比例、冷暖偏向） |
| `lr_doctor` | 自检，用中文说明哪里有问题、怎么处理 |

**这个版本不会修改任何照片**（没有任何写入工具；预览只写到 `C:\Users\<你>\LrMcp\previews`，不加入目录）。

## 🏗️ 结构

```
Claude / Codex ──(MCP, stdio)──▶ lrmcp.exe（Python 服务，本机 HTTP 队列 127.0.0.1:58770）
                                         ▲
                 Lightroom 插件（Lua）每 ≤10 s 来取任务、回结果
```

- 只在本机通信，随机口令，拒绝带 `Origin` 的请求（防网页乱连），端口独占（同一时间只支持一个服务实例）。
- 插件只执行白名单命令，不接受请求里的路径。
- 共享文件放 `C:\Users\<你>\LrMcp\`，**不放 AppData**（Claude 桌面版是 MSIX 应用，会重定向它启动的程序对 AppData 的写入，Lightroom 看不到）。

## 🧰 开发

```powershell
# 开发环境：conda 环境 lrmcp（mcp、pillow、pytest、pyinstaller）
cd server
C:\Users\<你>\miniconda3\envs\lrmcp\python.exe -m pytest -q          # 单元测试
python tests\acceptance.py        # 真实 Lightroom 验收（测试目录里选中一张照片）
python tests\smoke_stdio.py <命令>  # 通过真实 MCP 客户端冒烟测试

# 发布：测试 → lrmcp.exe → 插件打包 → 安装包（需要 Inno Setup 6）
powershell -ExecutionPolicy Bypass -File build.ps1
```

- 插件放在 `plugin/lrmcp.lrdevplugin`，开发时在 Lightroom 的 文件 → 增效工具管理器 → 添加。`devscripts/` 与 `DevRun.lua` 是**仅开发**的测试通道，发布包不含。
- 实验过程与结论：`docs/实验记录.md`；方案：`docs/方案.md`；实现中的发现与偏差：`docs/实现记录.md`。
- 版本号：服务在 `server/lightroom_mcp/__init__.py`，插件在 `plugin/.../Version.lua`（和 `Info.lua`），保持一致。

## 📦 安装（给朋友，免装 Python）

运行 `LrMCP-Setup-vX.Y.Z.exe`（**在普通环境双击运行**），按提示完成，然后重启 Lightroom 和 Claude / Codex。出问题让 Claude 调用 `lr_doctor`。

## ⚠️ 说明

- 需要自备 Lightroom Classic 与 Windows。
- Adobe SDK 文档与示例代码**不在本仓库内**，不要提交。
- Claude 桌面版暂不自动登记，见安装后的提示。
