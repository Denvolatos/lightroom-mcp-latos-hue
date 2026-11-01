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

## Pull requests

- One topic per PR, tests included, `python -m pytest -q` green.
- Say which Lightroom Classic version you tested on.
