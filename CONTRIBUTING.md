# Contributing / 参与贡献

Thanks for looking! This is a small hobby project; issues and pull requests are welcome.
这是个小项目，欢迎提 issue 和 PR。

## Ground rules / 约定

1. **Read-only first.** Anything that writes to a photo must be a whitelisted command with range checks, a backup of
   the old values, and tests against a *test* catalog. Never test on your real catalog.
   写入类功能必须有白名单、范围限制、改前备份，并只在测试目录上测试。
2. **Do not commit the Adobe SDK** (docs, samples, Lua compiler) or any code copied from Adobe's samples.
   不要提交 Adobe SDK 或示例代码。
3. Keep shared files out of `AppData` (see README, "Claude Desktop is an MSIX app").
4. Plug-in code stays small and boring: the Lightroom Lua sandbox is picky (no `os.getenv`, `os.execute`; most SDK
   calls need an async task; writes need `withWriteAccessDo`). `docs/实验记录.md` lists what was measured on LrC 15.2.
5. Messages shown to users are in Chinese (the code and tool names are English).
6. **License / 许可证：** 你提交的贡献按本项目的 GNU AGPL-3.0 授权（见 `LICENSE`）。
   Contributions you submit are licensed under the project's GNU AGPL-3.0 (see `LICENSE`).

## Setup / 开发环境

```powershell
conda create -n lrmcp python=3.12
conda activate lrmcp
pip install -e "./server[test]" pyinstaller
cd server
python -m pytest -q
```

Real-Lightroom checks (need Lightroom with a **test** catalog, the plug-in loaded, one photo selected):
`python tests/acceptance.py`, `SMOKE_FULL=1 python tests/smoke_stdio.py <server command>`.
The development bridge (`server/dev_bridge.py`, `server/dev_run.py`, `plugin/.../devscripts/`) lets you run Lua test
scripts inside Lightroom without clicking menus; see `docs/实现记录.md`.

## Pull requests / 提交 PR

- 一个 PR 一个主题，包含测试，`python -m pytest -q` 通过。
  One topic per PR, tests included, `python -m pytest -q` green.
- 请附一份**验证报告**（PR 模板里有填写项）。维护者根据报告评估可信度：可信度高的，不一定会在自己的机器上重复测试就合并；不够的，会提问或请你补充。
  Please attach a **verification report** (the PR template has a section for it). The maintainer judges how far to trust it: a
  well-evidenced report may be merged without repeating every test; otherwise you will be asked for more.

### 验证报告应包含 / What the report should contain

1. **环境 / Environment：** 操作系统、Lightroom Classic 版本、插件版本、用的是测试目录。
2. **改动范围 / Scope：** 改了什么，可能影响哪些现有行为，特别是是否涉及写照片、写文件、读路径、联网。
3. **验证方法 / How it was checked：** 可复现的步骤或命令，附原始输出或截图（不含个人路径、邮箱、口令、照片）。
4. **哪些在真机上验证了，哪些没有 / What was checked on real Lightroom and what was not：** 只靠单元测试或没验证的，写"待验证"。请不要夸大。
5. **已知限制和风险 / Known limits and risks。**

### 怎么评估 / How it is judged

维护者看：报告是否完整、能否复现、有没有真机证据、有没有如实标出没验证的部分、改动范围是否与说明一致。
The maintainer looks at: is it complete, reproducible, backed by real-Lightroom evidence, honest about what was not
checked, and does the change match its description.

**无论报告多完整，下面这类改动维护者仍会逐行审代码：** 涉及文件路径、写入照片或目录、网络访问、口令、权限。真机才暴露的问题（单元测试里的假 Lightroom 测不出）是这些改动最常见的风险。
**Whatever the report says, changes touching file paths, writes to photos or the catalog, network access, tokens or permissions are still read line by line.** Problems that only show on real Lightroom (a fake SDK cannot reveal them) are their usual risk.
