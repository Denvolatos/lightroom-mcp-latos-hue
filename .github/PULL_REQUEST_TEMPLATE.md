## What and why / 改了什么、为什么

## Checklist / 检查清单
- [ ] `python -m pytest -q` in `server/` is green / 单元测试通过
- [ ] Tested on Lightroom Classic version: ____ (a test catalog, not a real one / 用测试目录)
- [ ] No Adobe SDK files or copied Adobe sample code / 没有 Adobe SDK 文件或示例代码
- [ ] No personal paths, e-mail addresses, tokens or photos / 没有个人路径、邮箱、口令、照片
- [ ] Anything that writes to photos has a whitelist, range checks, a backup and tests / 写入类功能有白名单、范围检查、备份和测试
