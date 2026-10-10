# 数据格式

## 核心数据对象

### `IssueInfo`

| 字段 | 类型 | 说明 |
|------|------|------|
| `year` | int | 年份 |
| `volume` | int / null | 卷号，可为空 |
| `issue` | int | 期号；栏目抓取时整体 issue 可为 0，但不应作为文章显示期次 |
| `publishDate` | string | 刊出日期，可能为空 |

### `Article`

| 字段 | 类型 | 说明 |
|------|------|------|
| `journal` | string | 期刊名 |
| `year` | int | 文章来源年份 |
| `volume` | int / null | 文章来源卷号 |
| `issue` | int | 文章来源期号或总期号 |
| `section` | string | 栏目名；无栏目时可为 `未分类` |
| `title` | string | 题名 |
| `authors` | array | 作者列表 |
| `abstract` | string | 摘要，可能为空 |
| `startPage` / `endPage` | int | 起止页码 |
| `doi` | string | DOI，可能为空 |
| `issueDisplay` | string | 原站点显示的期次，例如 `20xx, x(x)` |
| `totalIssue` | int / null | 总期号或站点内部期号 |
| `sourceType` | string | `issue`、`channel` 或 `manual_curated` |
| `sourceNote` | string | 来源说明、降级原因或校正说明 |
| `articleUrl` | string | 文章页 URL |
| `pdfUrl` | string | PDF URL，可能为空 |
| `pdfSize` | string | PDF 大小，例如 `xKB` |
| `publishDate` | string | 发布日期，可能为空 |
| `capturedAt` | string | 抓取时间 |
| `status` | string | 文章处理状态：`presented` / `selected` / `imported` / `failed` |
| `zoteroKey` | string | 导入后的 Zotero key |
| `failReason` | string | 导入失败原因 |

字段定义以 `dhgleaner/models.py` 为准，本表提供语义说明。

## `data/pending.json`

`pending.json` 是对象，不是数组。

```json
{
  "capturedAt": "ISO 时间",
  "captureType": "issue/channel/manual_curated",
  "note": "本次抓取说明或校正原因",
  "markdown": "与 review.md 相同的筛选清单正文",
  "articles": [
    {
      "journal": "期刊名",
      "year": 2026,
      "volume": 6,
      "issue": 2,
      "issueDisplay": "原站点显示期次",
      "totalIssue": null,
      "sourceType": "issue",
      "sourceNote": "来源说明",
      "section": "栏目",
      "title": "文章题名",
      "authors": ["作者"],
      "abstract": "摘要",
      "articleUrl": "文章URL",
      "pdfUrl": "PDF URL",
      "status": "presented",
      "_globalIndex": 1
    }
  ]
}
```

使用规则：

- `review` 读取 `markdown` 渲染清单。
- `abstract` 按 `_globalIndex` 查 `articles`。
- `import --selection` 按 `_globalIndex` 选择文章。
- `captureType` 决定清单的解释方式（期次 / 栏目 / 人工校正）。
- `note` 记录栏目来源、人工校正、作者摘要缺失等情况。

**字段稳定性**：这是对外可见的数据格式，下游可能有依赖。任何字段增删或语义变化都应在 PR 描述里明确指出。

## `data/state.json`

用途：记录已处理的文章，避免重复导入。

```json
{
  "articles": {
    "期刊名|文章唯一键": {
      "title": "文章题名",
      "status": "imported/skipped/failed",
      "zoteroKey": "Zotero item key",
      "updatedAt": "ISO 时间"
    }
  },
  "issues": {
    "期刊名|期次键": {
      "status": "processed",
      "updatedAt": "ISO 时间"
    }
  }
}
```

实际字段以 `dhgleaner/state.py` 为准。

> 已知限制：`state.json` 没有归档或裁剪机制，长期使用会持续增长。

## `data/last_capture_status.json`

用途：记录最近一次抓取状态，尤其在失败或 `suspect` 时提醒旧清单未被覆盖。

```json
{
  "capturedAt": "ISO 时间",
  "status": "success/failed/suspect",
  "message": "状态说明",
  "reviewPath": "data/review.md",
  "pendingPath": "data/pending.json",
  "reviewIsStale": true,
  "results": []
}
```

## `data/backups/`

成功抓取覆盖旧 `pending.json` 与 `review.md` 之前自动生成。备份文件名包含原文件名与时间戳，便于回滚和排查误操作。

## `data/import_report.md`

保存最近一次真实导入的报告，便于回查 Zotero Key、重复跳过、失败原因与 PDF 处理状态。

报告区分四种 PDF 情形：

- 无 PDF 链接。
- 有 PDF 链接，但按期刊策略不自动下载。
- PDF 下载失败，已降级记录链接。
- PDF 已挂载。

**只有真正进入写入流程的导入才会产生该文件。** 预检中止（凭据缺失、Collection 缺失、无可导入文章）时不写报告，也不改动 `pending.json` 与 `review.md`。

## `data/title_match_report.md`

保存最近一次题名匹配确认表。它只说明题名与 `pending.json` 编号的匹配关系，**不代表已经导入 Zotero**。

内容包含：你的题名、匹配状态、命中的编号、命中的标题、匹配分数、唯一匹配编号汇总。
