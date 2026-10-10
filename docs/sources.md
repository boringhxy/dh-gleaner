# 来源与解析器

## 设计原则

- 能用配置表达的差异，优先写进 `dhjournal/defaults/config.json`。
- 只有页面结构明显不同、通用解析器确实不够时，才新增专用 parser。
- 所有解析器输出统一的 `Article` 对象。
- 不针对某个具体年份、卷号或期号写死逻辑；历史期定位应由模板、卷号规则或过刊页解析支持。

## 已支持的期刊

| 期刊 | parser | 主要抓取方式 | 备注 |
|------|--------|--------------|------|
| 数字人文研究 | `journy3` | 期次抓取 | 支持过刊页定位历史期次 |
| 数字人文 | `cnki_cbpt` | 当前公开页或手动 URL | 历史期可能受 CNKI 验证码限制 |
| 中国数字人文 | `generic_html` | 手动 URL / 人工校正 | 目录常跳转微信，作者摘要可能缺失 |
| 数位典藏与数位人文 | `generic_html` | 手动 URL / 人工校正 | Airiti 返回内容需强校验；TADH 公告页适合人工校正 |
| 图书馆杂志 | `magtech` | 期次抓取、栏目抓取 | 支持「数字人文」栏目分页 |
| 图书馆论坛 | `magtech` | 期次抓取 | 支持历史 URL 模板与卷号推算 |

## `journy3`

适用：Journy / Magtech 系站点中 HTML 结构与《数字人文研究》一致者。

能力：解析当前期次；从过刊页匹配历史期次；抽取栏目、题名、作者、页码、摘要与 PDF 链接。

## `cnki_cbpt`

适用：CNKI 采编平台的公开页面。

能力：抽取当前可访问页面中的文章目录；记录 PDF 下载链接，默认不自动下载。

限制：不绕过验证码和登录限制；历史期次若无法直接访问，需要你提供 URL 或人工整理。

## `magtech`

适用：Magtech / Journy 公开期刊系统。

能力：

- 解析当前期次与历史期次，从 archive 页查找目标期次。
- 用 `historyUrlTemplate` 构造历史目录 URL 作为 fallback。
- 用 `volumeYearBase` / `volumeBase` 推算卷号。
- 支持栏目页分页（识别 `changePage(...)` 并合并全部页）。
- 抽取每篇文章自己的 `issueDisplay` 与 `totalIssue`。

配置示例：

```json
{
  "historyUrlTemplate": "https://example.org/CN/Y{year}/V{volume}/I{issue}",
  "volumeYearBase": 2026,
  "volumeBase": 46,
  "channelSources": [
    {
      "channel": "栏目名",
      "url": "栏目页URL",
      "sourceType": "channel",
      "note": "来源说明"
    }
  ]
}
```

## `generic_html`

适用：没有稳定结构的目录页、公告页，或你人工整理的页面。

能力：

- 用容器白名单限制抽取区域。
- 用标题黑名单过滤导航、广告与平台推荐。
- 用域名白名单过滤跳转链接。
- 用必要页面文本校验目标来源。
- 作者与摘要缺失时做元数据降级。

质量要求：

- 标题中无关内容占比过高时，应标记 `suspect`。
- 页面缺少配置中的 `requiredPageText` 时，应标记 `suspect` 或直接失败。
- 不能把站点首页、数据库宣传页或 "Read More" 列表当作有效文章清单。

## 新增一份期刊

1. 判断来源类型：期次页、栏目页、公告页，还是平台检索页。
2. 先尝试用现有 parser 加配置表达差异。
3. 补充 `dhjournal/defaults/config.json`：站点、当前期 URL、过刊页、历史 URL 模板、栏目来源、PDF 策略、Zotero Collection 映射。
4. 增加样例 HTML 的单元测试，覆盖期次定位、文章抽取与质量校验。
5. 做真实冒烟测试时，先备份再恢复你现有的 `pending.json` / `review.md` —— 或者更稳妥地用一个临时的数据目录（`--data-dir`）。

如果最终需要新写 parser，请一并提交用于测试的样例 HTML（可以是你自己简化过的片段，不要直接提交整页线上内容）。
