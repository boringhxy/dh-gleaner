# Zotero 集成

## 集成方式

通过 Zotero Web API 工作。凭据放在 `config.local.json`：

```json
{
  "zotero": {
    "webLibraryId": "你的数字 userID",
    "webApiKey": "你的 API Key"
  }
}
```

真实 Key 只能保存在本地私密配置中，模板文件 `config.local.example.json` 里是占位符。

## Collection 策略

- 默认**不自动创建** Collection。
- Zotero 中应提前存在根目录与各期刊目录。
- 想批量补齐缺失目录，用显式命令 `dhgleaner init-collections`：默认只读预览缺哪些层级，加 `--yes` 才真正创建（`--journal` 可限定单刊）。这条命令与「导入时不擅自建目录」的红线互不影响。
- 导入时根据 `config.json` 的 `collectionPath` 与 `journalCollections` 定位目标目录。
- Collection 读取支持分页，避免目录数量超过 100 时漏查。
- 查重（`checkDuplicate`）同样翻页扫描并归一化比较标题，命中项多时不漏判。
- 若把 `zotero.autoCreateCollection` 设为 `true`，工具会逐级补齐缺失目录，并在导入报告中写明本次新建了哪些。

## 导入规则

- 只导入 `--selection` 中指定的编号（编号支持 `1,3,5` 与 `3-5` 区间，与 `screen --add` 同一套写法）。
- `--all` 仅用于你明确确认整期都要的场景。
- 导入前查重，避免重复创建条目。
- 写入失败按原因分档上报，不再统一报「创建条目失败」：连接中断会先回查一次——`POST /items` 有可能已提交、只是响应没回来，此时报「写入已完成，只是响应中断」并给出 key；凭据被拒（401/403/412/Invalid user ID）明说重试无用并指向 `dhgleaner init`。
- 读取 Zotero 目录本身失败时，导入直接暂停并报「无法读取 Zotero 目录」，不会被误写成「Collection 路径不存在」。
- 导入完成后更新 `state.json`。
- 每次真实导入保存 `data/import_report.md`。

## 字段映射

| `Article` 字段 | Zotero 字段 |
|----------------|-------------|
| `title` | title |
| `authors` | creators |
| `journal` | publicationTitle |
| `year` | date |
| `volume` | volume |
| `issue` / `issueDisplay` | issue / Extra |
| `startPage`-`endPage` | pages |
| `doi` | DOI |
| `abstract` | abstractNote |
| `articleUrl` | url |
| `pdfUrl` | 附件 URL 或 Extra |
| `sourceType` / `sourceNote` | Extra |

## Extra 字段

Extra 会记录：

- 原站点期次显示 `issueDisplay`。
- 总期号 `totalIssue`。
- 来源类型 `sourceType`。
- 来源说明 `sourceNote`。
- PDF 链接与失败原因。
- 人工校正或降级说明。

这些信息存在的意义是：当你几个月后回头看这条记录，能知道它当时是从哪个页面、以什么可信度抓来的。

## PDF 附件策略

- `autoDownloadPdf` 为 `true` 且 PDF 可下载时，尝试挂载文件附件。
- 文件存储配额不足或上传失败时，保留条目，创建 URL 附件或记录 PDF 链接。
- `autoDownloadPdf` 为 `false` 时，不下载 PDF，只记录链接。

## 错误处理

| 场景 | 处理 |
|------|------|
| Zotero 配置缺失 | `dhgleaner init` 交互式录入凭据；或 `doctor --zotero` 报出期望的配置文件路径与模板路径 |
| Collection 找不到 | 不导入，提示运行 `dhgleaner init-collections --yes` 补齐目录，或手动在 Zotero 中创建 |
| 文章重复 | 跳过或复用已有记录，写入导入报告 |
| PDF 上传失败 | 条目保留，Extra 记录失败原因 |
| 部分文章失败 | 不影响其他选中文章的导入 |
| 预检中止 | 不写入任何本地文件，返回中止原因 |

## 从 AI 客户端调用

`import_to_zotero` 是唯一会写 Zotero 的 MCP 工具，**默认拒绝执行**，需要同时给出 `confirm=true` 与 `dryRun=false`。建议流程是：先 `preview_import` 看清清单 → 让使用者确认 → 再带两个参数重试。详见 [mcp.md](mcp.md)。
