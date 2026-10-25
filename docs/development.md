# 开发说明

## 环境

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

`[dev]` 提供 ruff，`[mcp]` 是 MCP 层与相关测试所需的依赖。

## 目录结构

```text
dhgleaner/
├── cli.py              命令行入口：解析参数 -> 调 service -> 打印
├── service.py          业务编排层：只返回数据，不打印、不抛 SystemExit
├── capture.py          抓取主流程与质量校验
├── discovery.py        发现层：按刊的分层发现源，回答「最新的已知期次是哪一期」
├── importer.py         Zotero 导入与 PDF 处理
├── zotero_client.py    Zotero Web API 封装
├── presenter.py        渲染筛选清单与摘要
├── selection.py        选择解析（编号 / 题名 / 表格 / 全选）
├── selection_basket.py 筛选篮
├── review_spreadsheet.py  Excel 筛选表读写
├── title_matcher.py    题名归一化与匹配
├── models.py           Article / IssueInfo 数据模型
├── state.py            已处理状态记录
├── paths.py            数据目录解析
├── config.py           配置加载与凭据校验
├── validation.py       输入校验（抛 ValidationError）
├── parsers/            各站点解析器
├── mcp/                MCP 服务端与工具封装
└── defaults/           随包发布的配置模板
```

分层约定：`cli.py` 只负责解析参数与打印，`mcp/` 只负责包装与错误分类，业务逻辑一律下沉到 `service.py` 及同级模块。这样同一份逻辑才能同时被命令行和 MCP 复用。

## 测试

```bash
python -B -m unittest discover -s tests -v
ruff check .
```

两条都要干净。

测试不得依赖真实网络、真实 Zotero 账号或本机绝对路径；需要数据目录的用例一律使用 `tests/helpers.py` 提供的临时目录。

当前覆盖范围：

- state.json 原子写入与损坏隔离（不静默清空历史）。
- 筛选篮文件容错（脏 JSON 降级为空篮而非崩溃）。
- Zotero 查重翻页与归一化比较。
- 上手命令 init / init-collections（默认只预览，`--yes` 才写 Zotero）与凭据落盘。
- 四种当期解析器的样例解析（journy3 / cnki_cbpt / magtech / generic_html）。
- 散篇 harvest：关键词双表打标（数字人文任一命中 / 历史学+AI 共现 / 陷阱词排除 / 英文缩写大小写敏感）、前置条目过滤、`founder` API 字段映射、`journalx` 列表去重、`magtech` 的 `lunwen`/`dqml` 皮肤识别、`harvestJournal`/`harvestAll` 的 dhOnly 与轮转选择（`tests/test_harvest.py`，全部离线桩，不发网络请求）。
- Magtech 历史 URL archive 定位、模板 fallback 与卷号推算。
- Magtech 栏目分页、期次显示与 PDF 大小清洗。
- 抓取质量校验。
- 发现层 discover：volumn id 不能推期次、总期号（>12）忽略、只出现卷号不算一期、JournalX 空档页回显表头要拒绝、双月刊扫描起点按 issuesPerYear、微信推文没记录链接时「等人」而非失败、未标期次的推文不当前沿、时效提醒只警示不改抓取状态、每本刊的 kind/fetch 名与必填 url 校验（`tests/test_discovery.py`，全部离线桩，不发网络请求）。
- 选择解析（编号、题名、表格、全选、跳过）。
- 题名归一化与匹配确认流程。
- Zotero Collection 定位与 `collectionPlan` 只读预检。
- 数据目录四级解析。
- MCP 工具注册、失败分类、只读工具的只读性、导入双重闸门。
- 导入失败路径的零副作用。

## 冒烟测试

真实抓取会覆盖当前待筛数据，所以冒烟测试必须保护现场：

1. 优先用临时数据目录：`dhgleaner --data-dir /tmp/dhj-smoke capture …`，或设 `DHGLEANER_DATA_DIR`。
2. 若必须用默认数据目录，先记录 `data/pending.json` 与 `data/review.md` 的校验和。
3. 跑目标抓取，检查文章数、标题质量、期次显示、摘要与 PDF 链接。
4. 测试完成后恢复原待筛文件，除非你明确要保留本次结果。
5. 收工后比对校验和，确认现场未被动过。

**真实导入会写 Zotero**，除非你确定要写，否则不要在冒烟测试里执行 `import`。MCP 层可以用 stdio 探针离线验证：`initialize` → `notifications/initialized` → `tools/list` → `tools/call`，每行一个 JSON。

## 发布前检查

- 单元测试通过。
- `ruff check .` 通过。
- `doctor --zotero` 通过。
- README 与文档中的命令一致、可执行。
- `pending.json` 的 schema 文档未过期。
- 仓库中不含 `config.local.json` 的真实内容。
- 新增 parser 或配置有对应测试。
- 构建出的 wheel 不含内部文档，且带有 `dhgleaner/defaults/` 与 `dhgleaner/mcp/`。
- `dhgleaner --version` 打出的版本号与 `CHANGELOG.md` 里新建的版本节一致。

## 打包

```bash
python -m build
pip install dist/*.whl
```

- `python -m build`：生成 `dist/` 下的 sdist 与 wheel。
- `pip install dist/*.whl`：在干净环境里验证。

版本号**只写在 `dhgleaner/__init__.py` 的 `__version__`**：`pyproject.toml` 用 hatchling 的 dynamic version 从那里读，`dhgleaner --version`、MCP 的 `serverInfo` 与打包元数据用的是同一个值。改 `pyproject.toml` 里的版本不会生效。

wheel 需要包含 `defaults/`（配置模板）与 `mcp/`（服务端）。CI 的 `build` 任务会检查这两项，并确认内部文档没有被打进包里。
