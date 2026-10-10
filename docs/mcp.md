# MCP 工具参考

## 启动

```bash
pip install -e ".[mcp]"
dhgleaner-mcp        # 以 stdio 运行 MCP 服务端
```

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

数据目录解析规则与命令行一致（`--data-dir` 不适用于 MCP；用 `DHGLEANER_DATA_DIR` 环境变量指定）。几乎所有工具都会在返回值里带上 `dataDir`、`dataDirSource`、`configLocalPath`，便于客户端确认自己在读写哪个目录。

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

## 只读工具（8 个）

这些工具不写磁盘、不写 Zotero、不发网络请求（`run_doctor` 需显式开启检查）。

### `list_journals()`

列出支持的期刊、抓取方式与固有局限。返回 `count` 与 `journals[]`，每项含 `name`、`parser`、`hasCurrentIssueUrl`、`channels`、`autoDownloadPdf`、`pdfNote`、`publishRule`。

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

## 写本地工具（4 个）

只写本数据目录，**不写 Zotero**。

### `capture_issue(journal="", year=null, issue=null, volume=null, url="", selectAllJournals=false, dedupe=false, dryRun=true, limit=200)`

抓取某刊某期的目录与摘要，或按 `url` 抓指定目录页。`journal` 支持别名（`dhr` / `szrw` / `zgszrw` / `tadh` / `tsgzz` / `tsglt`）。

**`dryRun` 默认为 `true`**：只抓不落盘。确认无误后再用 `dryRun=false` 覆盖 `pending.json` / `review.md`。

返回 `journal`、`issue`、`status`、`quality`、`articleCount`、`reason`、`wrotePending`、`reviewPath`、`pendingPath`、`backups`、`articles[]`、`articlesTruncated`。

### `capture_channel(journal, channel, url="", dedupe=false, dryRun=true, limit=200)` → 前两个参数必填

按栏目抓取跨期清单，同样默认 `dryRun=true`。

### `export_review_spreadsheet(output="")`

把当前待筛清单导出为 Excel 勾选表。返回 `path`、`articleCount`、`columns`。没有待筛数据时返回 `no_pending`。

### `mark_pending_skipped(confirm=false)`

把当前待导入文章全部标记为已处理。**默认拒绝**；不带 `confirm=true` 时返回 `refused=true` 与 `requiresConfirmation=true`。

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

返回 `imported`、`skipped`、`failed`、`reportPath`、`createdCollections`、`report`。预检中止时返回 `wroteNothing=true`、`imported=0`，且**不写任何本地文件**。

## 一次典型的完整对话

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
