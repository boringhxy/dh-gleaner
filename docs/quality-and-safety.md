# 质量与安全

## 质量校验的目标

抓取结果必须**像一份文章清单**，而不是导航页、广告页、数据库推荐页、平台宣传页或错误页面。

## `suspect` 的判定条件

出现下列任一情况即标记为 `suspect`，并且**不覆盖**旧的 `review.md` / `pending.json`：

- 没有捕获到任何文章。
- 单期抓取把期次解析成 `0年第0期`。
- 标题里导航、广告、平台推荐类文本占比过高。
- 标题重复比例异常。
- 手动 URL 页面缺少配置要求的期刊名、IssueID 或栏目关键词。
- Airiti 等平台返回页面的标题、期刊名、IssueID 与目标不一致。

## 旧清单保护

- 成功抓取覆盖前，必须自动备份旧的 `data/pending.json` 与 `data/review.md`。
- 失败或 `suspect` 时只写 `data/last_capture_status.json`。
- 终端输出必须明确说明当前 `review.md` 是否仍是旧内容。

这条保护同样适用于导入：当导入在预检阶段中止（无可导入文章 / Zotero 连不上 / Collection 缺失）时，`pending.json`、`review.md` 与 `import_report.md` **都不写**。失败不该留下痕迹。

## PDF 安全降级

- 捕获阶段不下载 PDF。
- 导入阶段下载 PDF 前，先确认期刊配置允许自动下载。
- 下载后校验文件类型与大小。
- 下载失败、非 PDF、文件过小、被验证码拦截，或 Zotero 配额不足时，**不能导致元数据导入失败**。
- 降级信息写入 Zotero 的 Extra 字段，并可添加 `PDF待手动下载` 标签。

## 隐私与密钥

- `config.local.json` 保存 Zotero `webLibraryId` 与 `webApiKey`，不得公开。
- 文档、日志与终端摘要不得输出完整 API Key。
- 仓库与文档只展示配置模板，不展示真实用户 ID 与 Key。
- 工具只读取你的凭据，不发放、不代管、不上传。

## 合规边界

- 不绕过验证码、登录或付费权限。
- 不批量下载未授权全文。
- 不把 PDF 下载失败伪装成成功。
- 不自动创建 Zotero Collection（默认），避免条目落进错误目录。

## 可操作的失败信息

失败信息应当包含：

- 失败的期刊与目标（期次 / 栏目 / URL）。
- 失败所处的阶段：定位、下载页面、解析、质量校验、Zotero 导入，还是 PDF 挂载。
- 旧筛选清单是否被保留。
- 下一步建议，例如改用 `--url`、检查 Collection、转人工校正流程。

MCP 通道下这些信息以 `failureKind` 与 `suggestedAction` 的形式返回，便于客户端决定下一步，详见 [mcp.md](mcp.md)。
