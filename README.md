# 数字人文期刊采集器

[English](README.en.md) | **简体中文**

按刊按期巡检中文期刊目录页，**先筛选、后导入**：抓取目录与摘要生成人工筛选清单，只有你明确选中的文章才会写入 Zotero。

面向数字人文、图书情报与数字史学研究者的本地文献发现工具。不做实时监控，不做全文分析，不替你决定读什么。

## 它解决什么问题

研究者不缺「批量导入」，缺的是低噪音的文献发现流程。眼下的人工办法通常是：打开好几个期刊站点、找目标期次、逐篇看标题和摘要、复制信息、再决定要不要保存。这个过程重复、容易漏，还容易在 Zotero 里越堆越多无关条目。

本工具把这件事拆成三段：

1. **捕获** —— 按期次、栏目或手动目录页抓取文章目录、作者、栏目、页码、链接与摘要，生成 `data/review.md` 供你阅读。
2. **筛选** —— 你按编号挑选需要的文章，也可以导出 Excel 在表格软件里勾选。
3. **导入** —— 只把你选中的编号写入 Zotero；PDF 能下载就挂载，下载不了就降级记录链接和原因。

## 核心原则

- 捕获阶段**只做信息呈现**：不写 Zotero，不下载 PDF。
- 导入阶段**只处理你明确选中的编号**，不按顺序自动导入。
- 质量可疑的抓取结果**不覆盖**旧筛选清单，并留下状态文件提醒。
- Zotero Collection **复用既有目录**，默认不自动新建。
- **不绕过**验证码、登录限制或平台访问控制。

## 安装

需要 Python 3.10 或更高版本。

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

装好后会得到命令行入口 `dhgleaner`。想让 AI 客户端（Claude Desktop、Cherry Studio 等）直接调用，再装上 MCP 额外依赖：

```bash
pip install -e ".[mcp]"
```

那会额外提供 `dhgleaner-mcp` 入口。不加 `[mcp]` 不影响命令行使用。

> 用 `python -m dhgleaner` 与 `dhgleaner` 等价；若你没有激活虚拟环境，写成 `./.venv/bin/dhgleaner` 也可以。

## 快速开始

抓取和筛选**不需要任何 Zotero 凭据**，装上就能试：

```bash
dhgleaner capture --journal "数字人文研究" --year 2026 --volume 6 --issue 2   # 1. 抓当期目录
dhgleaner review                 # 2. 读清单，记下要导入的编号
```

要把选中的文章写进 Zotero 时，再配置你自己的凭据：

```bash
dhgleaner init                        # 3. 交互式录入凭据、测试连接、可选补齐 Collection 目录
dhgleaner import --selection "1,3,5"  # 4. 只导入选中的文章
```

`dhgleaner init` 把凭据写进数据目录下的 `config.local.json`（不会提交、不会上传、输入不回显）；
非交互环境下它会打印手动配置步骤而不阻塞。只想先看环境是否就绪，可运行 `dhgleaner doctor --zotero`。

## 命令参考

命令里的 `x` 都是占位符，运行时替换成实际数字，不要原样输入。

### 初始化

```bash
dhgleaner init                   # 交互式引导：录入 Zotero 凭据 → 测试连接 → 可选补齐目录 → 自检
dhgleaner init-collections       # 只读预览：列出各刊 Collection 路径缺哪些层级（不写 Zotero）
dhgleaner init-collections --yes # 确认后真正创建缺失目录
dhgleaner init-collections --journal "图书馆论坛" --yes   # 只补齐指定期刊
```

`init-collections` 默认只预览，加 `--yes` 才会写 Zotero；导入流程本身仍不会擅自建目录。

### 自检

```bash
dhgleaner doctor                 # 检查依赖、数据目录、配置文件
dhgleaner doctor --zotero        # 额外连接 Zotero，逐个检查期刊 Collection
dhgleaner doctor --network       # 额外做一次网络连通性检查
```

### 抓取

| 类型 | 适用场景 | 命令 |
|------|----------|------|
| 期次抓取 | 某刊某年某期 | `dhgleaner capture --journal "期刊名" --year x --issue x` |
| 卷期抓取 | 需要精确到卷号时 | `dhgleaner capture --journal "期刊名" --year x --volume x --issue x` |
| 栏目抓取 | 某刊某栏目跨期全量 | `dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"` |
| 散篇 harvest | 没有常设数字人文栏目、DH 内容散落在各栏目的图情/信息刊，按年枚举全目录再关键词筛 | `dhgleaner harvest --year 2026` |
| 手动目录页 | 官方公告页、微信目录、Airiti 等不稳定页面 | `dhgleaner capture --journal "期刊名" --url "目录页URL"` |

```bash
dhgleaner capture --journal "数字人文研究" --year x --issue x
dhgleaner capture --journal "数字人文研究" --year x --volume x --issue x
dhgleaner capture --journal "图书馆论坛" --year x --issue x
dhgleaner capture --journal "图书馆杂志" --year x --issue x
dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"
dhgleaner capture --journal "中国数字人文" --url "真实目录页URL"
dhgleaner capture --journal "数位典藏与数位人文" --url "真实目录页URL"
dhgleaner capture --all-journals --year x --issue x   # 显式抓取全部已配置期刊
```

不指定期刊的 `capture --year x --issue x` 会被拒绝——要抓全部必须显式加 `--all-journals`。

### 散篇 harvest（按年枚举 + 关键词筛）

有些图情/信息刊没有常设的「数字人文」栏目，DH 内容以散篇混在各栏目里，且当期目录页不稳定，只能逐年翻过刊库。`harvest` 就是为这类刊准备的第三种采集流程：按年枚举全年全目录 → 用关键词表打标 → 只留数字人文散篇。结果同样落到 `data/review.md` / `pending.json`，`screen` / `import` 下游照常可用。

```bash
dhgleaner harvest --year 2026                          # harvest 配置中所有 harvestOnly 散篇期刊
dhgleaner harvest --journal "现代情报" --year 2026       # 只 harvest 某一刊
dhgleaner harvest --year 2026 --all-catalog            # 保留全年全目录并打 DH 标签（不只留命中）
dhgleaner harvest --year 2026 --no-abstracts           # 不抓摘要，更快（关键词只按标题命中）
dhgleaner harvest --year 2026 --dedupe                 # 按 state.json 过滤已处理文章
dhgleaner harvest --year 2026 --dry-run                # 只打印，不覆盖 pending/review
```

`harvestOnly: true` 的期刊只进入 harvest 轮转，会被 `capture --all-journals` 与 `doctor --network` 跳过；对它们用 `capture` 抓当期会被拒绝并提示改用 `harvest`（除非显式给 `--url`）。

**关键词口径**（`dhgleaner/keywords.py`，capture 与 harvest 共用，给每篇文章打框架级双标签）。一篇文章算 DH，当且仅当**命中数字人文领域词**或**历史学+AI 共现**：

- **数字人文表**（`dhMatched`）= 领域词（数字人文/文化遗产/数字典藏/博物馆/GLAM/计量史学…），**任一命中**即算。
- **历史学+AI 表**（`histAiMatched`）= 历史词（古籍/甲骨/敦煌/方志/断代史…）+ 计算方法词（知识图谱/文本挖掘/GIS/深度学习/语义/本体…），采用**共现**判定：两侧各至少命中 1 个才算。
- **计算方法词不单独算 DH**：图情/信息刊里大量「AI in LIS」论文只用方法词、并无数字人文实质，单独命中会带来大量噪声，故方法词只在「历史+AI 共现」时作为计算侧计入。
- 命中用大小写敏感子串匹配（英文缩写 RAG/GIS/OCR 不会误落进 storage/logistics）；刻意排除「历史、古代、传统、文化、档案、记忆」等陷阱泛词。

### 筛选与导入

```bash
dhgleaner review                                        # 重新显示最近一次筛选清单
dhgleaner abstract --index 1                            # 查看某一篇的完整摘要
dhgleaner export-review                                 # 导出 Excel 筛选表 data/review_selection.xlsx
dhgleaner import --spreadsheet data/review_selection.xlsx          # 按表格勾选导入
dhgleaner import --spreadsheet data/review_selection.xlsx --dry-run # 只预览会导入哪些
dhgleaner import --selection "1,3,5"                    # 按编号导入
dhgleaner import --titles-file "titles.txt" --confirm-titles       # 按题名匹配导入
dhgleaner import --selection "都不要"                    # 本批全部不导入，标记为跳过
```

`export-review` 生成 `data/review_selection.xlsx`，在「筛选」页把「是否导入」列填「是」再执行 `import --spreadsheet`。

**筛选篮**适合边浏览边收集：

```bash
dhgleaner screen --list                     # 看当前清单
dhgleaner screen --search "关键词"           # 按关键词找编号
dhgleaner screen --add "1,3-5"              # 加进筛选篮
dhgleaner screen --remove "3"
dhgleaner screen --clear
dhgleaner screen --import                   # 把筛选篮里的文章导入
```

### 其他

```bash
dhgleaner --data-dir /path/to/dir <子命令>   # 临时指定数据目录
dhgleaner --help
```

`import --all` 仍然保留（整期全要时才用），但不是推荐流程。

## Zotero 配置

本工具通过 Zotero Web API 工作，使用**你自己的**凭据，工具只读取、不发放、不代管。

1. 打开 <https://www.zotero.org/settings/keys>。
2. 新建 API Key，勾选允许读写 library 的权限。
3. 在同一页找到数字形式的 userID。
4. 把仓库里的 `config.local.example.json` 复制成 `config.local.json`，填入两项：

```json
{
  "zotero": {
    "webLibraryId": "你的数字userID",
    "webApiKey": "你的API Key"
  }
}
```

`config.local.json` 已被 `.gitignore` 忽略，不会进版本库。**不要把 Key 写进任何公开文档或提交。**

配置完成后用 `dhgleaner doctor --zotero` 验证：它会读取全部 Collection 并逐个检查目标路径。

Zotero 中需要提前存在这些 Collection 路径：

```text
10-研究相关
└── 数字人文
    ├── 《数字人文研究》
    ├── 《数字人文》
    ├── 《中国数字人文》
    ├── 《数位典藏与数位人文》
    ├── 《图书馆杂志》
    └── 《图书馆论坛》
```

对应默认配置 `dhgleaner/defaults/config.json` 中的设置（如需自定义，在数据目录放一个同名 `config.json` 即可覆盖）：

```json
"collectionPath": ["10-研究相关", "数字人文"],
"journalCollections": {
  "数字人文研究": "《数字人文研究》",
  "数字人文": "《数字人文》",
  "中国数字人文": "《中国数字人文》",
  "数位典藏与数位人文": "《数位典藏与数位人文》",
  "图书馆杂志": "《图书馆杂志》",
  "图书馆论坛": "《图书馆论坛》"
}
```

若你希望工具补齐缺失的目录，可把 `zotero.autoCreateCollection` 设为 `true`；默认 `false`，找不到目录就暂停导入并说明原因。

## 支持的期刊

| 期刊 | 站点 | 解析器 | 期次定位 | 摘要 | PDF 策略 |
|------|------|--------|----------|------|----------|
| 数字人文研究 | `http://dhr.ruc.edu.cn/` | `journy3` | 支持过刊页自动定位历史期次 | 通常可抓取 | 导入选中文章时尝试下载并挂载 |
| 数字人文 | `https://szrw.cbpt.cnki.net/` | `cnki_cbpt` | 当前公开页可抓取；历史页可能需要用户提供 URL | 受 CNKI 页面限制，可能为空 | 默认不自动下载，导入时记录链接供手动下载 |
| 中国数字人文 | 名录未提供稳定公开目录页 | `generic_html` | 需要用户用 `--url` 指定可访问目录页 | 尽量抽取，通常为空 | 元数据降级为主 |
| 数位典藏与数位人文 | `http://www.tadh.org.tw/` | `generic_html` | 需要用户用 `--url` 指定可访问目录页 | 尽量抽取，通常为空 | 元数据降级为主 |
| 图书馆杂志 | `https://www.libraryjournal.com.cn/` | `magtech` | 支持期次页；支持「数字人文」栏目全量分页抓取 | 通常可抓取 | 导入选中文章时尝试下载并挂载 |
| 图书馆论坛 | `http://tsglt.zslib.com.cn/` | `magtech` | 可按配置推算卷号并使用历史 URL 模板定位公开过刊 | 通常可抓取 | 导入选中文章时尝试下载并挂载 |

以下散篇期刊标了 `harvestOnly: true`，只走 `harvest` 按年采集（不进 `capture --all-journals`，默认不下载 PDF）：

| 期刊 | 站点 | 解析器 | harvest 方式 |
|------|------|--------|--------------|
| 现代情报 | `https://www.xdqb.net/` | `founder` | 方正 rc-pub 开放 JSON API（getPeriodTree + 按栏目分组文章，内联摘要） |
| 情报科学 | `https://journal12.magtechjournal.com/jwk3_qbkx` | `magtech` | 过刊库 `ul.lunwen` 皮肤，逐篇抓详情摘要 |
| 中国图书馆学报 | `https://www.jlis.cn/jtlsc/ch/reader/` | `journalx` | `issue_list.aspx` 按季枚举，逐篇抓 `view_abstract` 详情 |
| 国家图书馆学刊 | `https://gtxk.nlc.cn/ch/reader/` | `journalx` | 同上 |
| 数字图书馆论坛 | `http://journals.istic.ac.cn/dlf/ch/reader/` | `journalx` | 同上 |
| 图书情报知识 | `https://dik.whu.edu.cn/jwk3/tsqbzs` | `magtech` | 过刊库 `div.dqml` 皮肤（DOI 式题名链接），逐篇抓详情摘要 |
| 信息资源管理学报 | `https://jirm.whu.edu.cn/jwk3/xxzyglxb` | `magtech` | 同上 |

新增期刊以配置驱动为主，解析器扩展方式见 `docs/sources.md`。

## 接入 AI 客户端（MCP）

本工具自带 MCP 服务端，可被支持 MCP 的 AI 客户端直接调用。

```bash
pip install -e ".[mcp]"
dhgleaner-mcp      # 以 stdio 方式运行 MCP 服务
```

客户端配置示例：

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "dhgleaner-mcp"
    }
  }
}
```

服务端暴露 14 个工具：

- **只读 8 个**：`list_journals`、`get_capture_status`、`list_pending_articles`、`get_article_abstract`、`search_pending_articles`、`preview_import`、`get_import_report`、`run_doctor`
- **写本地 5 个**：`capture_issue`、`capture_channel`、`harvest_year`、`export_review_spreadsheet`、`mark_pending_skipped`
- **写 Zotero 1 个**：`import_to_zotero`

`import_to_zotero` **默认拒绝执行**，必须同时给出 `confirm=true` 且 `dryRun=false` 才会真正写库。工具失败时返回带 `failureKind`（`network` / `blocked` / `captcha` / `empty_parse` / `issue_mismatch` / `not_configured` / `invalid_input` / `no_pending`）的结构化结果，便于客户端决定下一步。

完整参数与返回字段见 `docs/mcp.md`。

## 数据文件

默认在项目根目录的 `data/` 下（可换，见下）。

| 文件 | 作用 |
|------|------|
| `data/review.md` | 最近一次捕获生成的人工筛选清单，含目录与摘要 |
| `data/pending.json` | 结构化待筛数据，供 `review` / `abstract` / `import` 共用 |
| `data/state.json` | 已导入或跳过的记录，避免重复处理 |
| `data/last_capture_status.json` | 最近一次抓取状态；失败时标明 `review.md` 是否仍为旧内容 |
| `data/import_report.md` | 最近一次真实导入报告，含 Zotero Key、失败原因与 PDF 处理状态 |
| `data/title_match_report.md` | 最近一次题名匹配确认表（不代表已导入） |
| `data/review_selection.xlsx` | 导出的人工筛选表 |
| `data/backups/` | 成功捕获覆盖旧文件前的自动备份 |
| `logs/capture.log` | 运行日志（HTTP 日志已降噪，不会输出 API Key） |
| `tmp/` | PDF 临时下载目录，导入后清理 |

`pending.json` 不是数组而是对象：

```json
{
  "capturedAt": "ISO时间",
  "captureType": "issue/channel/manual_curated",
  "note": "本次抓取说明或校正原因",
  "markdown": "与 data/review.md 相同的筛选清单正文",
  "articles": [
    {
      "journal": "期刊名",
      "year": "年份数字",
      "volume": "卷号数字或 null",
      "issue": "期号数字或总期号",
      "issueDisplay": "原站点显示的年卷期，如 20xx, x(x)",
      "totalIssue": "总期号或 null",
      "sourceType": "issue/channel/manual_curated",
      "sourceNote": "来源说明或降级原因",
      "section": "栏目名，可能为未分类",
      "title": "文章标题",
      "authors": ["作者"],
      "abstract": "摘要文本，可能为空",
      "startPage": "起始页数字",
      "endPage": "结束页数字",
      "articleUrl": "文章页面 URL",
      "pdfUrl": "PDF URL，可能为空",
      "status": "presented/selected/imported/failed",
      "_globalIndex": "筛选清单中的编号"
    }
  ]
}
```

### 数据目录位置

按以下优先级解析，先命中先算：

1. 命令行 `--data-dir /path/to/dir`
2. 环境变量 `DHGLEANER_DATA_DIR=/path/to/dir`
3. 当前工作目录若含 `config.json` 或 `data/`，就用当前目录（兼容旧用法）
4. 兜底 `~/.dhgleaner`

## 抓取质量校验

保存前会检查抓取质量。以下情况标记为 `suspect`，**不覆盖**旧 `review.md` / `pending.json`：

- 期次解析为 `0年第0期`，且本次是单期抓取。
- 标题里导航、广告、平台推荐类文本占比过高。
- 标题重复比例异常。
- `generic_html` 配置了必要页面文本，但页面缺少目标期刊、IssueID 或栏目关键词。

遇到 `suspect` 时先看终端原因和 `data/last_capture_status.json`，确认真实目录页后用 `--url` 重试，或人工整理为 `manual_curated` 清单。

## PDF 降级策略

PDF 只在导入阶段处理。

- 期刊配置 `autoDownloadPdf: true` 且 PDF 可下载时，下载、校验并挂载到 Zotero。
- 下载结果不是 PDF、文件过小、网络失败、被验证码拦截，或 Zotero 存储配额不足时，**不会让整篇文章导入失败**。
- 降级后条目仍含标题、作者、期刊、年份、期号、页码、URL、摘要等基本信息，Extra 字段记录 PDF 链接和失败原因，并打上 `PDF待手动下载` 标签。
- 若 PDF 已下载但上传失败，会在条目下创建 URL 附件记录下载链接。

## 边界

- 《数字人文研究》历史期次支持较好，可从过刊页定位。
- 《数字人文》依赖 CNKI 采编平台公开页面；历史期次若被验证码或登录限制阻挡，需要你提供可访问的目录页 URL。
- 《图书馆论坛》已接入公开期刊系统，可按配置中的 `historyUrlTemplate` 与 `volumeYearBase` / `volumeBase` 推算历史期 URL。
- 《图书馆杂志》已接入通用 Magtech 解析器，「数字人文」栏目可用 `capture-channel` 抓取全量分页；官网偶发 412/SSL 拦截，必要时用 `--url` 指定真实目录页。
- 《中国数字人文》目录常跳转微信，作者和摘要可能无法稳定补全，按题名和链接降级。
- 《数位典藏与数位人文》Airiti 页面若返回平台宣传内容会被质量校验拦截，优先用 TADH 官方公告页或人工整理清单。
- 本工具**不会**破解验证码、绕过登录，或替代学校账号权限。

## 开发

```bash
pip install -e ".[dev,mcp]"      # mcp 可选：不装则跳过 1 项 server 注册校验，其余用例照常

python -B -m unittest discover -s tests -v    # 单元测试
ruff check .                                  # 静态检查
```

贡献方式与红线见 `CONTRIBUTING.md`；安全问题上报见 `SECURITY.md`；版本变更见 `CHANGELOG.md`。

## 许可

MIT，见 [LICENSE](LICENSE)。
