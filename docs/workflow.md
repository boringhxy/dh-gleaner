# 工作流

## 总体流程

```text
指定期刊/年/期（或栏目、目录页 URL，或按年 harvest 散篇期刊）
  -> 抓取目录、摘要与元数据
  -> 抓取质量校验
  -> 成功：生成筛选清单，并备份旧清单
     失败或可疑：保留旧清单，写入状态文件
  -> 阅读 review.md，选定编号
  -> 只把选中的文章导入 Zotero
  -> PDF 可下载则挂载，否则记录链接与原因
```

> 首次使用：抓取与筛选无需任何凭据，可直接开始。等到要写入 Zotero 时，先运行 `dhgleaner init` 录入你自己的凭据（必要时再用 `dhgleaner init-collections --yes` 补齐目录）。

## 工作流 A：期次抓取

适用：查看某刊某年某期的文章目录。

```bash
dhgleaner capture --journal "期刊名" --year x --issue x
dhgleaner capture --journal "期刊名" --year x --volume x --issue x
```

输入：

- `--journal`：必须是 `config.json` 中已配置的期刊。未配置的刊名会被拒绝。
- `--year`：目标年份。
- `--volume`：可选，供按卷号定位或推算历史 URL 的期刊使用。
- `--issue`：目标期号。

输出：

- 成功：更新 `data/review.md`、`data/pending.json`，覆盖前自动备份旧文件。
- 失败或可疑：写 `data/last_capture_status.json`，**不覆盖**旧清单。

## 工作流 B：栏目抓取

适用：目标是一个跨期栏目，而不是单一期次。

```bash
dhgleaner capture-channel --journal "图书馆杂志" --channel "数字人文"
dhgleaner capture-channel --journal "期刊名" --channel "栏目名" --url "栏目页URL"
```

前提：

- 解析器必须是 `magtech`。其他皮肤会直接返回「当前解析器为 xxx，暂不支持 capture-channel」并记为一次失败。
- 栏目页地址来自该刊配置的 `channelSources`；没配就必须给 `--url`。
- 默认配置里写了 `channelSources` 的只有《图书馆杂志》。它的栏目页 `showChannelArticle.do` 用普通请求就能读到（2026-10-22 复测：单页 40 篇、合并分页后 67 篇），上面第一条命令可以直接跑；该刊被 412 挡住的是期次入口 `current.shtml`，与栏目页无关。

要求：

- 栏目页可能分页，解析器需自动合并全部页。
- 每篇文章记录自己的 `issueDisplay`、`totalIssue`、页码与来源说明。
- 栏目整体不能被渲染成 `0年第0期`。
- 重复文章应被过滤，或在质量校验中被指出。

## 工作流 C：人工校正抓取

适用：官方公告页、微信目录页、Airiti/TADH 页面，以及你自己整理的目录页。

```bash
dhgleaner capture --journal "期刊名" --url "目录页URL"
```

要求：

- 用 `generic_html` 或专用 parser 尽量抽取题名、作者、摘要、链接。
- 页面若是平台宣传、导航或推荐内容，应标记为 `suspect`。
- 作者或摘要缺失时仍可生成清单，但要在 `note` 或 `sourceNote` 里说明降级原因。

## 工作流 D：散篇 harvest（按年枚举 + 关键词筛）

适用：没有常设「数字人文」栏目、DH 内容以散篇混在各栏目，且当期目录页不稳定、只能逐年翻过刊库的图情/信息刊（配置里标了 `harvestOnly: true`）。

```bash
dhgleaner harvest --year 2026
dhgleaner harvest --journal "现代情报" --year 2026
dhgleaner harvest --year 2026 --all-catalog
dhgleaner harvest --year 2026 --no-abstracts
dhgleaner harvest --year 2026 --dedupe
dhgleaner harvest --year 2026 --dry-run
```

不带 `--journal` 时轮转所有 `harvestOnly` 散篇期刊。参数含义：

- `--all-catalog`：保留全年全目录并打 DH 标签，不做关键词过滤。
- `--no-abstracts`：不抓摘要，关键词只按标题命中。
- `--dedupe`：按 `state.json` 过滤已处理文章。
- `--dry-run`：只打印，不覆盖 `pending.json` / `review.md`。

要求与行为：

- 解析器需实现 `supportsHarvest` 与 `harvestYear(year)`：`founder`（方正 JSON API）、`journalx`（`issue_list.aspx` 按季枚举）、`magtech`（过刊库 `volumn_N.shtml`，自动识别 `ul.lunwen` / `div.dqml` / 经典三种皮肤）。
- 全年文章先过前置条目过滤（目次/卷首语/征稿等），再用 `dhgleaner/keywords.py` 打 `dhMatched` / `histAiMatched` 双标签；`dhOnly`（默认）只留命中文章。
- 逐期/逐篇请求按 `harvestDelay` 限速（`capture-channel` 的分页之间同样限速）；只读公开页与开放 API，不绕过验证码/登录，不写 Zotero、不下 PDF。
- 重试按 `retryInterval` 指数退避，上限 300 秒；站点返回 `Retry-After` 时优先听站点的。401/403/412 一次都不重试，直接判定为「拒绝自动化」。
- 结果同样经质量闸门（`captureType="harvest"` 跳过「year==0」误抓判定）落到 `data/review.md` / `pending.json`，`screen` / `import` 下游照常可用。
- `harvestOnly` 期刊会被 `capture --all-journals` 与 `doctor --network` 跳过；对它们用 `capture` 抓当期会被拒绝并提示改用 `harvest`（除非显式给 `--url`）。

## 筛选与导入

```bash
dhgleaner review
dhgleaner abstract --index x
dhgleaner export-review
dhgleaner import --selection "1,3-5"
dhgleaner import --selection "都不要"
```

依次是：重新显示最近一次清单、查看某一篇的完整摘要、导出 Excel 勾选表、按编号导入、本批全部跳过。

任何一条导入路径都能加 `--dry-run`：只预览，不写 Zotero，也不改 `pending.json` 与 `state.json`。`--selection` 传空值会被拒绝——「都不要」必须明确写出来，否则 shell 里没展开的变量就会把整张清单标成已跳过。编号写法与 `screen --add` 共用一个解析器：`1,3,5` 和 `3-5` 都吃，写错了报「导入范围有误」，不会静默选成 0 篇。

筛选篮适合边看边收：

```bash
dhgleaner screen --list
dhgleaner screen --search "关键词"
dhgleaner screen --add "1,3-5"
dhgleaner screen --import
```

## 异常流程

| 情况 | 工具的行为 |
|------|-----------|
| 目标期次自动定位失败 | 提示改用 `--url`，并尽量给出推测的目录 URL |
| 网络失败 | 不覆盖旧清单，记录失败状态 |
| 页面质量可疑 | 标记 `suspect`，不覆盖旧清单 |
| Zotero Collection 缺失 | 导入前中止，提示运行 `dhgleaner init-collections --yes` 补齐或手动创建目录 |
| Zotero 凭据未配置 | 导入前中止，**不写任何本地文件**，提示运行 `dhgleaner init` 录入凭据 |
| PDF 下载或上传失败 | 保留 Zotero 条目，记录 PDF 链接与失败原因 |

失败的返回信息会包含：失败的期刊与目标、失败所处的阶段（定位 / 下载 / 解析 / 质量校验 / Zotero 导入 / PDF 挂载）、旧清单是否保留、以及下一步建议。

## 状态与退出码

抓取失败目前仍返回退出码 0，脚本若要判断成败，请读取 `data/last_capture_status.json` 的 `status` 字段（`success` / `suspect` / `failed`）。这一点属于已知限制，见 [CHANGELOG](../CHANGELOG.md)。
