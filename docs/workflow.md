# 工作流

## 总体流程

```text
指定期刊/年/期（或栏目、目录页 URL）
  -> 抓取目录、摘要与元数据
  -> 抓取质量校验
  -> 成功：生成筛选清单，并备份旧清单
     失败或可疑：保留旧清单，写入状态文件
  -> 阅读 review.md，选定编号
  -> 只把选中的文章导入 Zotero
  -> PDF 可下载则挂载，否则记录链接与原因
```

> 首次使用：抓取与筛选无需任何凭据，可直接开始。等到要写入 Zotero 时，先运行 `dhjournal init` 录入你自己的凭据（必要时再用 `dhjournal init-collections --yes` 补齐目录）。

## 工作流 A：期次抓取

适用：查看某刊某年某期的文章目录。

```bash
dhjournal capture --journal "期刊名" --year x --issue x
dhjournal capture --journal "期刊名" --year x --volume x --issue x   # 需要卷号时
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
dhjournal capture-channel --journal "图书馆杂志" --channel "数字人文"
```

要求：

- 栏目页可能分页，解析器需自动合并全部页。
- 每篇文章记录自己的 `issueDisplay`、`totalIssue`、页码与来源说明。
- 栏目整体不能被渲染成 `0年第0期`。
- 重复文章应被过滤，或在质量校验中被指出。

## 工作流 C：人工校正抓取

适用：官方公告页、微信目录页、Airiti/TADH 页面，以及你自己整理的目录页。

```bash
dhjournal capture --journal "期刊名" --url "目录页URL"
```

要求：

- 用 `generic_html` 或专用 parser 尽量抽取题名、作者、摘要、链接。
- 页面若是平台宣传、导航或推荐内容，应标记为 `suspect`。
- 作者或摘要缺失时仍可生成清单，但要在 `note` 或 `sourceNote` 里说明降级原因。

## 筛选与导入

```bash
dhjournal review                        # 重新显示最近一次清单
dhjournal abstract --index x            # 查看某一篇的完整摘要
dhjournal export-review                 # 导出 Excel 勾选表
dhjournal import --selection "1,3,5"    # 按编号导入
dhjournal import --selection "都不要"    # 本批全部跳过
```

筛选篮适合边看边收：

```bash
dhjournal screen --list
dhjournal screen --search "关键词"
dhjournal screen --add "1,3-5"
dhjournal screen --import
```

## 异常流程

| 情况 | 工具的行为 |
|------|-----------|
| 目标期次自动定位失败 | 提示改用 `--url`，并尽量给出推测的目录 URL |
| 网络失败 | 不覆盖旧清单，记录失败状态 |
| 页面质量可疑 | 标记 `suspect`，不覆盖旧清单 |
| Zotero Collection 缺失 | 导入前中止，提示运行 `dhjournal init-collections --yes` 补齐或手动创建目录 |
| Zotero 凭据未配置 | 导入前中止，**不写任何本地文件**，提示运行 `dhjournal init` 录入凭据 |
| PDF 下载或上传失败 | 保留 Zotero 条目，记录 PDF 链接与失败原因 |

失败的返回信息会包含：失败的期刊与目标、失败所处的阶段（定位 / 下载 / 解析 / 质量校验 / Zotero 导入 / PDF 挂载）、旧清单是否保留、以及下一步建议。

## 状态与退出码

抓取失败目前仍返回退出码 0，脚本若要判断成败，请读取 `data/last_capture_status.json` 的 `status` 字段（`success` / `suspect` / `failed`）。这一点属于已知限制，见 [CHANGELOG](../CHANGELOG.md)。
