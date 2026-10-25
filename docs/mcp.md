# MCP 工具参考

## 启动

装上 `[mcp]` 额外依赖后即有 `dhgleaner-mcp` 入口，它以 stdio 运行 MCP 服务端：

```bash
pipx install "dh-gleaner[mcp] @ git+https://github.com/boringhxy/dh-gleaner.git"
```

开发环境用 `pip install -e ".[dev,mcp]"`。

客户端配置：

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "dhgleaner-mcp"
    }
  }
}
```

**客户端通常不继承你 shell 的 PATH**，裸命令名可能报「找不到命令」。用 `command -v dhgleaner-mcp` 查出绝对路径填进去。

数据目录解析规则与命令行一致，但 `--data-dir` 不适用于 MCP，只能用 `DHGLEANER_DATA_DIR` 环境变量指定；客户端的工作目录也不是你在命令行里用的那个，所以如果你一直在某个项目目录下抓取，务必在客户端配置里显式给出数据目录，否则它会落到兜底的 `~/.dhgleaner`：

```json
{
  "mcpServers": {
    "dh-gleaner": {
      "command": "/Users/you/.local/bin/dhgleaner-mcp",
      "env": {
        "DHGLEANER_DATA_DIR": "/path/to/your/working-directory"
      }
    }
  }
}
```

几乎所有工具都会在返回值里带上 `dataDir`、`dataDirSource`、`configLocalPath`，便于客户端确认自己在读写哪个目录。

## 返回契约

所有工具返回**扁平字典**，只有两种形状：

```jsonc
// 成功
{ "ok": true, "...": "该工具自己的字段" }

// 失败
{ "ok": false, "failureKind": "blocked", "message": "……", "suggestedAction": "……" }
```

### `failureKind` 取值

| 取值 | 含义 | 客户端宜采取的动作 |
|------|------|--------------------|
| `network` | 网络不通、超时、重试耗尽 | 稍后重试 |
| `blocked` | 站点拒绝自动化访问（401/403/412） | 不要重试，改用 `url` 指定单期目录页 |
| `captcha` | 页面需要验证码或登录 | 不要重试，请使用者提供公开可访问的目录页 |
| `empty_parse` | 页面能打开但解析不出文章 | 确认目录页是否正确，或该期是否尚未上线 |
| `issue_mismatch` | 抓到的期次与目标不符，疑似误抓 | 核对 `year` / `issue`，旧清单未被覆盖 |
| `not_configured` | 缺少 Zotero 凭据等前置配置 | 引导配置后再试 |
| `invalid_input` | 参数不合法 | 修正参数 |
| `no_pending` | 没有待筛或待导入数据 | 先抓取目录 |
| `unknown` | 未归类 | 查看 `message` 与 `run_doctor` 输出 |

`suggestedAction` 是与 `failureKind` 配套的自然语言建议，可直接转述给使用者。

抓取类工具（`capture_issue` / `capture_channel` / `harvest_year`）的结果里带两个逐刊字段，用于表达「部分刊没成功」；整批为 `suspect` / `failed` 时它们是 `ok: false` 载荷的一部分，`success` 时也在：

```jsonc
{
  "ok": true,
  "status": "suspect",
  "failures": [{ "journal": "图书馆杂志", "stage": "resolve", "kind": "blocked", "detail": "…" }],
  "blockedJournals": ["图书馆杂志"]
}
```

`kind` 为 `blocked` 表示站点明确拒绝自动化（重试无用），为 `failed` 表示临时故障。`blockedJournals` 是 `failures` 里 `kind == "blocked"` 的刊名快捷方式，便于客户端直接决定「别再自动重试这几本」。

## 只读工具（9 个）

这些工具不写磁盘、不写 Zotero。例外只有 `discover_latest`：判断「最新的已知期次」必须访问公开页面，这是它的用途；它默认 `record=false` 仍然不落盘，请求预算与 `capture_*` 相同，并受同一套红线约束（401/403/412 立即失败，不绕过验证码与登录）。`run_doctor` 的联网检查需显式开启。

### `list_journals()`

列出支持的期刊、抓取方式与固有局限。返回 `count` 与 `journals[]`，每项含 `name`、`parser`、`hasCurrentIssueUrl`、`channels`、`autoDownloadPdf`、`pdfNote`、`publishRule`。

### `discover_latest(journal="", record=false)`

**回答「这本刊有没有新刊」的唯一入口。**按每刊配置的分层发现源逐个探测，`journal` 留空即探测全部。返回 `journals[]`，每项含 `frontier`（最新已知期次及其来源、tier、URL）、`official`（官方逐篇页的最新一期）、`sources[]`（各源状态、报告的期次、`lagIssues` 比最新已知期次落后几期）、`nextAction`（直接把这一期抓下来的命令）。

- `waitingForHuman[]`：该刊只有人工型源（如公众号目录推文），需要先用 `record_issue_url` 贴链接。
- `noFrontier[]`：自动源全部落空的刊，应视为需要人工看一眼。
- `record=true` 才把结论写入 `state.json` 的 `latestKnown`；之后 `capture_*` 抓到更旧的期次时会在返回值里带 `freshnessWarnings[]`。

不要用 `list_journals()` 的 `currentIssueUrl` 判断有没有新刊：官方逐篇页常比真实公告晚几期（实测《数字人文》官方停在 2025 年第 4 期时，公众号已公告 2026 年第 3 期）。

### `get_capture_status()`

最近一次抓取的状态。返回 `hasStatus`、`capturedAt`、`status`、`message`、`reviewIsStale`、`results`、`pendingArticleCount`。`reviewIsStale` 为真时，当前清单是旧内容。

### `list_pending_articles(journal="", issue="", limit=200, offset=0, includeUrls=false)`

列出当前待筛文章。`issue` 按显示期次做子串匹配；`includeUrls` 打开后才返回 `articleUrl` 与 `pdfUrl`。返回 `total`、`returned`、`offset`、`articles[]`、`reviewIsStale`。

每行的字段：`index`、`title`、`journal`、`issue`、`section`、`authors`、`pages`、`hasAbstract`、`abstractLength`、`hasPdf`、`status`。

### `get_article_abstract(index)` → 必填

读取某篇待筛文章的完整信息与摘要。`index` 是筛选清单里的编号（从 1 开始）。编号越界时返回 `invalid_input` 并附 `maxIndex`。摘要为空时 `note` 会说明可能的原因。

### `search_pending_articles(query, limit=50)` → `query` 必填

按关键词搜索题名、作者、栏目与摘要。

### `preview_import(selection, titles, titlesFile, spreadsheet, selectAll, useBasket, confirmTitles, limit=200)`

**只读**预览将要导入的文章，绝不写入任何地方。至少要给出一种范围，否则返回 `invalid_input`。

返回的 `status` 取值：

| `status` | 含义 |
|----------|------|
| `resolved` | 已解析出可导入的文章 |
| `empty` | 没有选中任何文章 |
| `needs_confirm` | 题名未能唯一匹配 |
| `title_confirm_required` | 题名匹配成功，但还需要显式确认 |
| `skipped_all` | 选择是「都不要」 |
| `invalid` | 表格校验失败 |

### `get_import_report(maxChars=8000)`

读取上一次真实导入的报告。返回 `path`、`length`、`truncated`、`report`。从未导入过时返回 `no_pending`。

### `run_doctor(checkZotero=false, checkNetwork=false)`

自检数据目录、配置模板、依赖与可写性。`checkZotero` 会真实连接 Zotero 逐刊检查 Collection（只读，不新建目录）；`checkNetwork` 会真实抓取各刊当期目录页做解析验证。

## 写本地工具（6 个）

只写本数据目录，**不写 Zotero**。

抓取预览不写清单或 state；`run_doctor` 只读估计目录权限，不创建目录或探针。服务进程启动日志另行管理。

### `capture_issue(journal="", year=null, issue=null, volume=null, url="", selectAllJournals=false, dedupe=false, dryRun=true, limit=200)`

抓取某刊某期的目录与摘要，或按 `url` 抓指定目录页。`journal` 支持别名（`dhr` / `szrw` / `zgszrw` / `tadh` / `tsgzz` / `tsglt`）。

**`dryRun` 默认为 `true`**：只抓不落盘。确认无误后再用 `dryRun=false` 覆盖 `pending.json` / `review.md`。

返回 `journal`、`issue`、`status`、`quality`、`articleCount`、`reason`、`wrotePending`、`reviewPath`、`pendingPath`、`backups`、`articles[]`、`articlesTruncated`。

### `capture_channel(journal, channel, url="", dedupe=false, dryRun=true, limit=200)` → 前两个参数必填

按栏目抓取跨期清单，同样默认 `dryRun=true`。

### `harvest_year(year=null, journal="", withAbstracts=true, dhOnly=true, dedupe=false, dryRun=true, limit=200)` → `year` 必填

按年枚举散篇期刊的全年目录，并用关键词表打标筛选，同样默认 `dryRun=true`、不写 Zotero、不下 PDF。面向标了 `harvestOnly` 的图情/信息刊（现代情报、情报科学、中国图书馆学报、国家图书馆学刊、数字图书馆论坛、图书情报知识、信息资源管理学报）。

- `journal` 留空 → harvest 配置中所有 `harvestOnly` 期刊；指定时须支持 harvest（解析器为 `founder` / `journalx` / `magtech`），否则返回 `invalid_input`。
- `dhOnly=true`（默认）只保留命中关键词表的文章；`false` 保留全年全目录并打标签。
- `withAbstracts=false` 更快，但关键词只按标题命中。

返回字段与 `capture_issue` 一致（`status` / `quality` / `articleCount` / `articles[]` 等）。

### `export_review_spreadsheet(output="")`

把当前待筛清单导出为 Excel 勾选表。返回 `path`、`articleCount`、`columns`。没有待筛数据时返回 `no_pending`。

### `mark_pending_skipped(confirm=false)`

把当前待导入文章全部标记为已处理。**默认拒绝**；不带 `confirm=true` 时返回 `refused=true` 与 `requiresConfirmation=true`。

### `record_issue_url(journal, url, source="")` → 前两个参数必填

记下人工发现的最新一期链接（如公众号目录推文），只写 `state.json`，不抓网页、不覆盖待筛清单。之后 `discover_latest` 才会把这一期当作最新已知期次，并在官方逐篇页滞后时报出落后几期。

只能记到人工型发现源（该刊 `discovery.sources` 里 `tier=1` 或 `fetch=manual` 的那一项）上；把链接记到官方源会让「官网说它是最新」和「有人贴了个链接」两件事混成一件，之后的时效判断就不可信。该刊没有人工型源时返回 `invalid_input`。

## 写 Zotero 工具（1 个）

### `import_to_zotero(selection="", titles="", titlesFile="", spreadsheet="", selectAll=false, useBasket=false, confirmTitles=false, confirm=false, dryRun=true, limit=200)`

**唯一会写 Zotero 的工具，默认拒绝执行。**

写入需要**同时**满足两个条件：

- `confirm=true`
- `dryRun=false`

只给其中一个时会返回 `refused=true`，并在 `note` 里指出还差哪个条件，此时**不会调用任何写入逻辑**。

建议流程：

1. 调 `preview_import` 拿到将要导入的清单。
2. 把清单交给使用者确认。
3. 确认后调 `import_to_zotero(selection="…", confirm=true, dryRun=false)`。

返回 `imported`、`skipped`、`failed`、`reportPath`、`createdCollections`、`report`。远端处理后本地保存失败时返回 `failureKind=local_save_failed`，保留远端计数和报告，不声称未写入。预检中止时返回 `wroteNothing=true`、`imported=0`，且**不写任何本地文件**。

## 一次典型的完整对话

```text
用户：数字人文最近有没有新刊

1. discover_latest(journal="数字人文")      -> frontier 2025年第4期（官方页），tier1 微信源 waitingForHuman
2. record_issue_url(journal="数字人文", url="https://mp.weixin.qq.com/s/…", source="wechat_toc")
                                            -> 把用户贴进来的目录推文记到本地
3. discover_latest(journal="数字人文")      -> frontier 变成 2026年第3期，官方页报 lagIssues=3
4. 按 nextAction 走：这一期官方逐篇页还没上线，先告诉用户只能按公众号题录人工挑
```

```text
用户：帮我看看《数字人文研究》2026 年第 2 期有什么

1. list_journals()                          -> 确认这本刊在支持列表里
2. capture_issue(journal="数字人文研究", year=2026, volume=6, issue=2)
                                            -> dryRun 默认 true，先看会抓到什么
3. capture_issue(…, dryRun=false)           -> 确认无误后落盘
4. list_pending_articles(journal="数字人文研究")  -> 展示编号与题名
5. get_article_abstract(index=3)            -> 用户想看第 3 篇的摘要

用户：导入第 1、3、5 篇

6. preview_import(selection="1,3,5")        -> 展示清单，等用户确认
7. import_to_zotero(selection="1,3,5", confirm=true, dryRun=false)
                                            -> 写入 Zotero
8. get_import_report()                      -> 回读报告
```

第 6 步不能省。`preview_import` 与 `import_to_zotero` 之间隔着的就是使用者的确认，这是本项目最正式的一条边界。
