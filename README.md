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

需要 Python 3.10 或更高版本。装好后会得到命令行入口 `dhgleaner`；再加 `[mcp]` 会多一个 `dhgleaner-mcp` 入口，供 AI 客户端调用——不加 `[mcp]` 不影响命令行使用。

**推荐：用 pipx 一行装好**，不用 clone，装进独立环境，不碰系统 Python：

```bash
pipx install "dh-gleaner @ git+https://github.com/boringhxy/dh-gleaner.git"
pipx install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

没有 pipx 就先装它（`python3 -m pip install --user pipx`，macOS 也可以 `brew install pipx`），或者用 uv：

```bash
uv tool install "dh-gleaner @ git+https://github.com/boringhxy/dh-gleaner.git"
uv tool install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

**也可以 clone 后用虚拟环境**：

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install ".[mcp]"
```

`-e`（可编辑安装）只在你要改代码时用：`pip install -e ".[dev,mcp]"`。纯粹使用的话不需要 `-e`。

升级到最新提交：

```bash
pipx upgrade dh-gleaner
```

装的是 git 源，若 pip 缓存导致没拉到最新提交，改用 `pipx install --force "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"` 强制重装；uv 对应 `uv tool upgrade dh-gleaner --reinstall`。

装完先自检一次，它会自动建好数据目录并告诉你缺什么：

```bash
dhgleaner doctor
```

> 用 `python -m dhgleaner` 与 `dhgleaner` 等价；若你没有激活虚拟环境，写成 `./.venv/bin/dhgleaner` 也可以。

## 快速开始

抓取和筛选**不需要任何 Zotero 凭据**，装上就能试。先抓一期目录，再把清单显示出来、记下要导入的编号：

```bash
dhgleaner capture --journal "数字人文研究" --year 2026 --volume 6 --issue 2
dhgleaner review
```

要把选中的文章写进 Zotero 时，再配置你自己的凭据。`init` 会交互式录入凭据、测试连接，并可选补齐 Collection 目录；`import --selection` 只导入你选中的那几篇：

```bash
dhgleaner init
dhgleaner import --selection "1,3,5"
```

`dhgleaner init` 把凭据写进数据目录下的 `config.local.json`（不会提交、不会上传、输入不回显）；
非交互环境下它会打印手动配置步骤而不阻塞。只想先看环境是否就绪，可运行 `dhgleaner doctor --zotero`。

## 命令参考

命令里的 `x` 都是占位符，运行时替换成实际数字，不要原样输入。

### 初始化

```bash
dhgleaner init
dhgleaner init-collections
dhgleaner init-collections --yes
dhgleaner init-collections --journal "图书馆论坛" --yes
```

- `init`：交互式引导，录入 Zotero 凭据 → 测试连接 → 可选补齐目录 → 自检。
- `init-collections`：只读预览，列出各刊 Collection 路径缺哪些层级，**不写 Zotero**。
- `init-collections --yes`：确认后真正创建缺失目录；可用 `--journal` 只补齐指定期刊。

`init-collections` 默认只预览，加 `--yes` 才会写 Zotero；导入流程本身仍不会擅自建目录。

### 自检

```bash
dhgleaner --version
dhgleaner doctor
dhgleaner doctor --zotero
dhgleaner doctor --network
```

- `--version`：打印版本号；报 bug 时请连同 `doctor` 输出一起贴上。
- `doctor`：检查依赖、数据目录、配置文件。
- `doctor --zotero`：额外连接 Zotero，逐个检查期刊 Collection。
- `doctor --network`：额外做一次网络连通性检查。

### 抓取

| 类型 | 适用场景 | 命令 |
|------|----------|------|
| 期次抓取 | 某刊某年某期 | `dhgleaner capture --journal "期刊名" --year x --issue x` |
| 卷期抓取 | 需要精确到卷号时 | `dhgleaner capture --journal "期刊名" --year x --volume x --issue x` |
| 全刊轮转 | 一次抓完配置里所有非 `harvestOnly` 的刊 | `dhgleaner capture --all-journals --year x --issue x` |
| 栏目抓取 | 某刊某栏目跨期全量 | `dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"` |
| 散篇 harvest | 没有常设数字人文栏目、DH 内容散落在各栏目的图情/信息刊，按年枚举全目录再关键词筛 | `dhgleaner harvest --year 2026` |
| 手动目录页 | 官方公告页、微信目录、Airiti 等不稳定页面 | `dhgleaner capture --journal "期刊名" --url "目录页URL"` |

不指定期刊的 `capture --year x --issue x` 会被拒绝——要抓全部必须显式加 `--all-journals`。

`capture-channel` 只对 Magtech 皮肤的期刊开放，其他皮肤会直接报「当前解析器为 xxx，暂不支持 capture-channel」；栏目页地址取自该刊配置的 `channelSources`，没配就必须用 `--url` 指定。默认配置里写了 `channelSources` 的只有《图书馆杂志》，它的**栏目页可以正常抓取**（2026-10-22 复测：单页 40 篇、跨页合并 67 篇，年卷期与页码都在），上表那条命令是能直接跑的——被 412 挡住的是它的**所有期次入口**（`current.shtml`、`home.shtml`、`CN/volumn/volumn_N.shtml` 都收得到 412，2026-10-24 复测），过刊索引页 `showOldVolumn.do` 则可正常读取，见「边界」。

### 发现最新一期（discover）

「抓不到最新一期」有两种完全不同的原因：站点确实没上线新刊，或者**我们看的源本来就比真实公告晚几期**。只看一个入口无法区分这两件事，所以每本刊在配置里都写了一组分层发现源（`discovery.sources`），`discover` 逐个问「你知道的最新一期是第几期」，再按层汇总：

- **tier 1**：最早公告（如公众号目录推文），通常只有题录、没有逐篇文章页。
- **tier 2**：官方逐篇页（期刊自建系统 / CNKI 采编平台），能直接抓正文。
- **tier 3**：聚合与镜像站（如 DHCN），最滞后，但常是唯一有摘要的一层。

```bash
dhgleaner discover                        # 探测全部期刊
dhgleaner discover --journal "数字人文"    # 只看一刊
dhgleaner discover --json                 # 结构化输出，供脚本与 Agent 消费
dhgleaner discover --no-record            # 只报告，不写 state.json 的 latestKnown
```

输出每刊一行「最新已知期次 ← 哪个源」，各源标出比它落后几期，末尾直接给出拿到这一期该跑的命令（`capture --url` / `capture-channel` / `harvest`）。期次一律按 (年, 期) 取最大值，**不按 CMS 内部 id 或页面顺序推断**（实测《情报科学》id 1275 是第2期、id 1273 反而是第5期）。

tier 1 里有些源站外不可列举——微信公众号没有文章列表接口，往期推文也不互链，所以新推文只能由人贴进来：

```bash
dhgleaner discover --journal "数字人文" --record-url "https://mp.weixin.qq.com/s/xxxx" --source wechat_toc
```

记下之后 `discover` 就能把这一期认作最新已知期次，并在官方页仍停在旧期时明确报出「落后 3 期」。之后任何一次 `capture` / `capture-channel` 抓到早于该记录的期次，都会在输出里追加一条 ⏳ 时效提醒（不改变抓取状态与退出码——抓到旧期不是抓坏了，清单本身有效）。

### 散篇 harvest（按年枚举 + 关键词筛）

有些图情/信息刊没有常设的「数字人文」栏目，DH 内容以散篇混在各栏目里，且当期目录页不稳定，只能逐年翻过刊库。`harvest` 就是为这类刊准备的第三种采集流程：按年枚举全年全目录 → 用关键词表打标 → 只留数字人文散篇。结果同样落到 `data/review.md` / `pending.json`，`screen` / `import` 下游照常可用。

```bash
dhgleaner harvest --year 2026
dhgleaner harvest --journal "现代情报" --year 2026
dhgleaner harvest --year 2026 --all-catalog
dhgleaner harvest --year 2026 --no-abstracts
dhgleaner harvest --year 2026 --dedupe
dhgleaner harvest --year 2026 --dry-run
```

| 参数 | 作用 |
|------|------|
| 不加参数 | harvest 配置中所有 `harvestOnly` 散篇期刊 |
| `--journal "现代情报"` | 只 harvest 某一刊 |
| `--all-catalog` | 保留全年全目录并打 DH 标签，不只留命中的 |
| `--no-abstracts` | 不抓摘要，更快；关键词只按标题命中 |
| `--dedupe` | 按 `state.json` 过滤掉已处理过的文章 |
| `--dry-run` | 只打印，不覆盖 `pending.json` / `review.md` |

`harvestOnly: true` 的期刊只进入 harvest 轮转，会被 `capture --all-journals` 与 `doctor --network` 跳过；对它们用 `capture` 抓当期会被拒绝并提示改用 `harvest`（除非显式给 `--url`）。

**关键词口径**（`dhgleaner/keywords.py`，capture 与 harvest 共用，给每篇文章打框架级双标签）。一篇文章算 DH，当且仅当**命中数字人文领域词**或**历史学+AI 共现**：

- **数字人文表**（`dhMatched`）= 领域词（数字人文/文化遗产/数字典藏/博物馆/GLAM/计量史学…），**任一命中**即算。
- **历史学+AI 表**（`histAiMatched`）= 历史词（古籍/甲骨/敦煌/方志/断代史…）+ 计算方法词（知识图谱/文本挖掘/GIS/深度学习/语义/本体…），采用**共现**判定：两侧各至少命中 1 个才算。
- **计算方法词不单独算 DH**：图情/信息刊里大量「AI in LIS」论文只用方法词、并无数字人文实质，单独命中会带来大量噪声，故方法词只在「历史+AI 共现」时作为计算侧计入。
- 命中用大小写敏感子串匹配（英文缩写 RAG/GIS/OCR 不会误落进 storage/logistics）；刻意排除「历史、古代、传统、文化、档案、记忆」等陷阱泛词。

### 筛选与导入

| 命令 | 作用 |
| --- | --- |
| `dhgleaner review` | 重新显示最近一次筛选清单 |
| `dhgleaner abstract --index 1` | 查看某一篇的完整摘要 |
| `dhgleaner export-review` | 导出 Excel 筛选表 `data/review_selection.xlsx` |
| `dhgleaner import --spreadsheet data/review_selection.xlsx` | 按表格勾选导入 |
| `dhgleaner import --spreadsheet data/review_selection.xlsx --dry-run` | 只预览会导入哪些 |
| `dhgleaner import --selection "1,3-5"` | 按编号导入（支持区间） |
| `dhgleaner import --titles-file "titles.txt" --confirm-titles` | 按题名匹配导入 |
| `dhgleaner import --selection "都不要"` | 本批全部不导入，标记为跳过 |

`--dry-run` 对以上任何一条导入路径都有效：只预览、不写 Zotero，也不改动待筛清单和 `state.json`。`--selection` 不接受空值，「都不要」必须明确写出来。编号写法与 `screen --add` 一致——`1,3,5` 与 `1-7` 都支持，解析不了会直接报错，不会静默选成 0 篇。

`export-review` 生成 `data/review_selection.xlsx`，在「筛选」页把「是否导入」列填「是」再执行 `import --spreadsheet`。

**筛选篮**适合边浏览边收集：先 `--list` 看当前清单、`--search` 按关键词找编号、`--add` / `--remove` 增删条目，最后 `--import` 把篮子里的文章导入。`--clear` 清空。

```bash
dhgleaner screen --list
dhgleaner screen --search "关键词"
dhgleaner screen --add "1,3-5"
dhgleaner screen --remove "3"
dhgleaner screen --clear
dhgleaner screen --import
```

### 其他

`--data-dir` 只对本次调用生效，用于临时指定数据目录：

```bash
dhgleaner --data-dir /path/to/dir <子命令>
dhgleaner --help
```

`import --all` 仍然保留（整期全要时才用），但不是推荐流程。

## Zotero 配置

本工具通过 Zotero Web API 工作，使用**你自己的**凭据，工具只读取、不发放、不代管。

1. 打开 <https://www.zotero.org/settings/keys>。
2. 新建 API Key，勾选允许读写 library 的权限。
3. 在同一页找到数字形式的 userID。
4. 运行 `dhgleaner init`，按提示粘贴这两项——输入不回显，存完会立刻测一次连接。

想手动配置，就把下面两项写进**数据目录**下的 `config.local.json`（默认是 `~/.dhgleaner/config.local.json`；`dhgleaner doctor` 会打印确切路径，并给出可复制的模板路径）：

```json
{
  "zotero": {
    "webLibraryId": "你的数字userID",
    "webApiKey": "你的API Key"
  }
}
```

`config.local.json` 不进版本库、不上传、日志里也不会出现。**不要把 Key 写进任何公开文档、issue 或提交。**

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
| 图书馆杂志 | `https://www.libraryjournal.com.cn/` | `magtech` | 期次入口 `current.shtml` 被 412 拦、自动定位不可用；「数字人文」栏目分页可正常抓取 | **期次抓取当前不可自动完成**：反爬前置检查对 `current.shtml` 稳定返回 412，需用 `--url` 指定可直接打开的目录页；栏目抓取不受影响 | 导入选中文章时尝试下载并挂载 |
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

本工具自带 MCP 服务端，可被支持 MCP 的 AI 客户端直接调用。装上 `[mcp]` 额外依赖即可：

```bash
pipx install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

装好后 `dhgleaner-mcp` 即以 stdio 方式运行 MCP 服务。

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

两个实际会踩到的点：

- **客户端通常不继承你 shell 的 PATH**，写裸命令名可能报「找不到命令」。用 `command -v dhgleaner-mcp` 查出绝对路径填进去，例如 `/Users/you/.local/bin/dhgleaner-mcp`。
- **客户端的工作目录不是你跑命令行的那个目录**，而 `--data-dir` 对 MCP 不适用。如果你在某个项目目录里用命令行抓过数据，想让 AI 客户端读到同一批清单，就在配置里显式指定数据目录，否则它会用兜底的 `~/.dhgleaner`：

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "/Users/you/.local/bin/dhgleaner-mcp",
      "env": {
        "DHGLEANER_DATA_DIR": "/path/to/your/工作目录"
      }
    }
  }
}
```

几乎所有工具的返回值里都带 `dataDir`、`dataDirSource`、`configLocalPath`，可以让客户端确认自己读写的是哪个目录。

服务端暴露 16 个工具：

- **只读 9 个**：`list_journals`、`discover_latest`、`get_capture_status`、`list_pending_articles`、`get_article_abstract`、`search_pending_articles`、`preview_import`、`get_import_report`、`run_doctor`
- **写本地 6 个**：`capture_issue`、`capture_channel`、`harvest_year`、`export_review_spreadsheet`、`mark_pending_skipped`、`record_issue_url`
- **写 Zotero 1 个**：`import_to_zotero`

`discover_latest` 是「这本刊有没有新刊」的唯一入口：它会按分层发现源逐源探测（这是它的用途，请求预算与 capture 相同、受同一套不绕过验证码/登录的红线约束），默认 `record=false` 因此不写任何文件；设为 `true` 才把结论写入 `state.json` 的 `latestKnown`。问「有没有新刊」不要只看 `list_journals` 的 `currentIssueUrl`。

`import_to_zotero` **默认拒绝执行**，必须同时给出 `confirm=true` 且 `dryRun=false` 才会真正写库。工具失败时返回带 `failureKind`（`network` / `blocked` / `captcha` / `empty_parse` / `issue_mismatch` / `not_configured` / `invalid_input` / `no_pending`）的结构化结果，便于客户端决定下一步。

完整参数与返回字段见 `docs/mcp.md`。

## 数据文件

默认位置取决于安装方式：clone 后在项目根目录的 `data/` 下，用 pipx / uv 装的则在 `~/.dhgleaner/data/` 下。完整解析规则见文末「数据目录位置」。

| 文件 | 作用 |
|------|------|
| `data/review.md` | 最近一次捕获生成的人工筛选清单，含目录与摘要 |
| `data/pending.json` | 结构化待筛数据，供 `review` / `abstract` / `import` 共用 |
| `data/state.json` | 已导入或跳过的记录，避免重复处理；另存发现层的 `latestKnown`（该刊最新已知期次）与人工贴入的期次链接 |
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

保存前会**逐刊**检查抓取质量——13 本里 12 本抓崩、1 本正常，聚合看仍是「有文章」，但那批结果不能覆盖上一次完整的清单。以下情况标记为 `suspect`，**不覆盖**旧 `review.md` / `pending.json`：

- 期次解析为 `0年第0期`，且本次是单期抓取。
- 标题里导航、广告、平台推荐类文本占比过高。
- 标题或摘要含解码替换符 U+FFFD，说明站点编码被判读错。
- 标题重复比例异常。
- `generic_html` 配置了必要页面文本，但页面缺少目标期刊、IssueID 或栏目关键词。
- 批量抓取中部分期刊失败，但仍有其他刊出了结果。
- 栏目分页触到 `maxChannelPages` 上限，清单可能只覆盖前若干页。

遇到 `suspect` 时先看终端原因和 `data/last_capture_status.json`，确认真实目录页后用 `--url` 重试，或人工整理为 `manual_curated` 清单。

### 退出码

`capture` / `capture-channel` / `harvest` 的退出码可以直接给 cron、CI 或脚本判断：

| 退出码 | 含义 |
|--------|------|
| 0 | 全部期刊抓取成功且质量正常 |
| 1 | 本次没抓到可用结果（参数错误同样是 1） |
| 2 | 命令行参数本身不合法（argparse） |
| 3 | 抓到了但质量存疑，或部分期刊失败——旧清单未被覆盖，需要人工看一眼 |

`data/last_capture_status.json` 里的 `failures` 会逐刊给出 `stage` 与 `kind`；`kind` 为 `blocked` 表示站点明确拒绝自动化（401/403/412），重试无用，只能换 `--url` 或转人工。

`discover` 只有 0 与 1：1 表示某刊的自动发现源全部落空，需要人工看一眼。只有人工型源（如公众号目录推文）的期刊不算失败——那是在等人贴链接，不是抓坏了。

## PDF 降级策略

PDF 只在导入阶段处理。

- 期刊配置 `autoDownloadPdf: true` 且 PDF 可下载时，下载、校验并挂载到 Zotero。
- 下载结果不是 PDF、文件过小、网络失败、被验证码拦截，或 Zotero 存储配额不足时，**不会让整篇文章导入失败**。
- 降级后条目仍含标题、作者、期刊、年份、期号、页码、URL、摘要等基本信息，Extra 字段记录 PDF 链接和失败原因，并打上 `PDF待手动下载` 标签。
- 若 PDF 已下载但上传失败，会在条目下创建 URL 附件记录下载链接。

## 边界

- 《数字人文研究》历史期次支持较好，可从过刊页定位。
- 《数字人文》是清华大学 + 中华书局办的集刊（无 ISSN），**最早的公告在公众号「DH数字人文」的目录推文里**；CNKI 采编平台（`szrw.cbpt.cnki.net`）通常晚几期，DHCN（dhcn.cn）是微信内容的转载层但唯一带摘要。所以「cbpt 首页还是去年那期」不等于「没有新刊」——这一档只能用 `discover` 的分层结果判断，最新推文的 URL 需要人工 `--record-url` 贴进来（公众号在微信外没有可列举的文章列表，往期推文也不互链）。历史期次若被验证码或登录限制阻挡，需要你提供可访问的目录页 URL。
- 《图书馆论坛》已接入公开期刊系统，可按配置中的 `historyUrlTemplate` 与 `volumeYearBase` / `volumeBase` 推算历史期 URL。
- 《图书馆杂志》已接入通用 Magtech 解析器。**412 打在所有期次入口上**——`current.shtml`、`home.shtml`、`CN/volumn/volumn_N.shtml` 都会收到 412，不是偶发（2026-10-24 复测），所以 `capture --journal 图书馆杂志 --year x --issue x` 走不通；同一站点的过刊索引页 `showOldVolumn.do`（`discover` 用它发现最新期）与栏目页 `showChannelArticle.do` 用普通请求就能读到，`capture-channel --journal 图书馆杂志 --channel 数字人文` 是该刊目前唯一可自动拿到正文的路径。按项目红线，我们**不绕过**该检查；要抓某一期只能由你用浏览器打开目录页后以 `--url` 指定，且仍可能失败。该刊的 `historyUrlTemplate` 含 `{volume}` 但缺 `volumeYearBase` / `volumeBase`，按年期自动定位过刊也不可用——报错信息会直接说明这一点。
- 《中国数字人文》目录常跳转微信，作者和摘要可能无法稳定补全，按题名和链接降级。
- 《数位典藏与数位人文》Airiti 页面若返回平台宣传内容会被质量校验拦截，优先用 TADH 官方公告页或人工整理清单。
- 本工具**不会**破解验证码、绕过登录，或替代学校账号权限。

## 反馈与求助

三种 issue 模板对应三类需求，选对模板能省一轮来回：

| 你想做的事 | 去处 |
|------------|------|
| 报 bug：抓取结果不对、命令报错、导入失败、Excel 表打不开 | [Bug 报告](https://github.com/boringhxy/dh-gleaner/issues/new?template=bug_report.yml) |
| 希望接入某本还没支持的期刊 | [新增期刊源](https://github.com/boringhxy/dh-gleaner/issues/new?template=new_journal.yml) |
| 安装、配置、Zotero、MCP 用法咨询 | [使用咨询](https://github.com/boringhxy/dh-gleaner/issues/new?template=question.yml) |
| 安全漏洞：凭据可能泄漏的路径、绕过导入确认闸门 | 邮件 `boringhxy@163.com`，见 [SECURITY.md](SECURITY.md)，**不要**开公开 issue |
| 想改代码、加解析器 | [CONTRIBUTING.md](CONTRIBUTING.md)，先读硬性红线 |

报 bug 时最有用的是三样东西，请一并贴上：

1. `dhgleaner --version` 的输出——同一个版本的行为可能差别很大。
2. `dhgleaner doctor` 的完整输出——已脱敏，不含你的 API Key。命令本身装不上时，改成粘贴安装报错。
3. `data/last_capture_status.json` 的内容——它说明本次抓取是成功、失败还是 `suspect`，旧的 `review.md` 是否仍然有效，以及每本没抓到的刊具体卡在哪个阶段。

**任何情况下都不要把 `config.local.json` 的内容或 Zotero API Key 贴进 issue。**

提「新增期刊源」时最关键的一项，是一个**不登录就能打开的真实目录页 URL**——接入工作量几乎完全取决于目录页能否被稳定读到。模板还会问到站点平台（决定能否直接复用现有六种 parser 之一）、DH 内容是集中在固定栏目还是散落在各栏目（决定走 `capture-channel`、`capture` 还是 `harvest`）、摘要与 PDF 的可得性。这些正是写 parser 需要的信息，详见 `docs/sources.md`。

本工具不做的事，提需求也不会被接受：破解验证码、模拟登录、绕过付费墙、批量下载受版权保护的全文。这条红线写在 CONTRIBUTING.md 里，也是这个项目能公开存在的前提。

## 开发

```bash
git clone https://github.com/boringhxy/dh-gleaner.git
cd dh-gleaner
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"
python -B -m unittest discover -s tests -v
ruff check .
```

`[dev]` 提供 `ruff`，`[mcp]` 是 MCP 层与其测试所需的依赖。不装 `mcp` 也能跑测试，只是会跳过 1 项 server 注册校验，其余用例照常。
最后两条分别是单元测试与静态检查，提交前两条都要干净。

贡献方式与红线见 `CONTRIBUTING.md`；安全问题上报见 `SECURITY.md`；版本变更见 `CHANGELOG.md`。提 PR 时会用到 `.github/PULL_REQUEST_TEMPLATE.md` 里的检查清单。

## 许可

MIT，见 [LICENSE](LICENSE)。
