<!--
提交前请先读 CONTRIBUTING.md。这个模板对应其中的「提交 Pull Request」四条要求，
外加两条本地检查。填不完的项目请说明原因，不要直接删掉。
-->

## 这个 PR 解决了什么问题

<!-- 一句话说清动机。如果对应某个 issue，写 Closes #123 -->

## 怎么验证的

<!--
运行过什么命令、抓过哪本真实期刊、导入是否用了 --dry-run。
涉及网络抓取的改动，请说明用了哪个真实来源做冒烟测试。
-->

## 本地检查

- [ ] `ruff check .` 干净
- [ ] `python -B -m unittest discover -s tests -v` 全部通过
- [ ] 新行为有对应单元测试；如果是修 bug，先补了一个能复现该 bug 的失败用例
- [ ] 测试没有依赖真实网络、真实 Zotero 账号或本机绝对路径（数据目录用 `tests/helpers.py`）
- [ ] 没有把真实抓取结果（`data/` 下的 `pending.json`、`review.md`、整页线上 HTML）提交进仓库
- [ ] `CHANGELOG.md` 的 `[Unreleased]` 里记了一笔
- [ ] 文档同步：命令或流程有变化时，`README.md` / `README.en.md` / `docs/` 一起改了

## 边界确认

- [ ] 没有让捕获阶段写 Zotero，也没有削弱 `import` 的显式确认闸门
- [ ] 没有让失败或 `suspect` 的抓取结果覆盖已有筛选清单
- [ ] 没有涉及识别、绕过验证码，或模拟登录、复用登录态、绕过付费墙
- [ ] `dhgleaner/mcp/` 下没有新增 `print`（会损坏 stdio 上的 JSON-RPC）

## 数据结构变更

<!--
是否改动了 data/pending.json、data/state.json、data/last_capture_status.json 的字段，
或 Article / IssueInfo 模型？没有就写「无」。
有的话请逐条列出新增/改名/删除的字段——下游 screen、import、MCP 工具都可能依赖。
-->

无
