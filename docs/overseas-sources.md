# 海外数字人文来源与访问说明

核实日期：2026-11-15。范围限定为数字人文会议、附属工作坊及数字人文专业期刊。

本次按官方组织、正式出版档案与稳定标识核实来源。目录已收录22个来源，其中9个实现了采集适配，13个仅登记入口。适配器经过离线测试，但本环境终端DNS失败，浏览器验证也未完成，不能宣称实时采集已跑通。

## 使用

```bash
dhgleaner sources
dhgleaner sources --source chr --json
dhgleaner capture-source --source chr --year 2025 --dry-run
dhgleaner capture-source --source humanistica --year 2026 --dry-run
dhgleaner capture-source --source dhtech --year 2025 --dry-run
dhgleaner capture-source --source dhnb --year 2026 --url https://journals.uio.no/dhnbpub/issue/view/dhnb2026 --dry-run
dhgleaner capture-source --source dsh --year 2026 --dry-run
```

去掉 `--dry-run` 后才保存标准 pending.json/review.md；旧清单先备份，失败、年份/来源不符、缺少文章元数据或分页不完整时保留旧清单。继续用 review、screen、export-review 与按编号选择的 import 流程。采集不下载PDF、不写Zotero。

Anthology需要单一卷目录，每届目录不同；默认链接只是已经核实的特定年份，不代表以后自动定位。DHNB必须指定单期目录；同一出版系列也包含专题工作坊和期刊专题，不能一律标成DHNB年会论文。Crossref按ISSN、年份枚举已登记元数据，不保证覆盖原刊全部文章，缺失摘要保持为空。DHQ若元数据缺失，需后续适配官方XML，不能把空结果解释为该年未出版。

## 来源清单

| ID | 来源 | 类型 | 接入方式 | 官方档案/入口 | 全文与账号 |
|---|---|---|---|---|---|
| chr | Computational Humanities Research | conference | 卷目录＋单篇引用元数据 | [官方入口](https://anthology.ach.org/volumes/vol0003/) | 开放；无需机构账号 |
| humanistica | Humanistica | conference | 卷目录＋单篇引用元数据 | [官方入口](https://anthology.ach.org/volumes/vol0004/) | 开放；无需机构账号 |
| dhtech | Digital Humanities Tech Symposium | workshop | 卷目录＋单篇引用元数据 | [官方入口](https://anthology.ach.org/volumes/vol0002/) | 开放；无需机构账号 |
| dhnb | Digital Humanities in the Nordic and Baltic Countries | conference | 指定单期目录＋单篇引用元数据 | [官方入口](https://journals.uio.no/dhnbpub/issue/archive) | 开放；无需机构账号 |
| adho | ADHO Digital Humanities | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://zenodo.org/records/22656106) | 开放；无需机构账号 |
| dhd | DHd | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://github.com/DHd-Verband/DHd-Abstracts-2025) | 开放；无需机构账号 |
| eadh | EADH Conference | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://eadh.org/conferences) | 开放；无需机构账号 |
| dhbenelux | DH Benelux | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://journal.dhbenelux.org/volumes/) | 开放；无需机构账号 |
| ach | ACH Conference | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://ach2026.ach.org/en/program/) | 开放；无需机构账号 |
| jadh | JADH Conference | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://www.jadh.org/conferences) | 开放；无需机构账号 |
| aiucd | AIUCD | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://amsacta.unibo.it/id/eprint/8980/) | 开放；无需机构账号 |
| csdh | CSDH/SCHN | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://csdh-schn.ca/2026-csdh-schn-annual-conference-program/) | 开放；无需机构账号 |
| dha | Digital Humanities Australasia | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://aa-dh.org/conferences/dha2025/) | 开放；无需机构账号 |
| hdh | Humanidades Digitales Hispánicas | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://humanidadesdigitaleshispanicas.es/portfolio/congreso-hdh-2025/) | 开放；无需机构账号 |
| redhd | Encuentro de Humanistas Digitales | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://humanidadesdigitales.net/encuentros-rhd/) | 开放；无需机构账号 |
| dhasa | DHASA Conference | conference | 官方入口登记；未启用自动拆篇 | [官方入口](https://upjournals.up.ac.za/index.php/dhasa/issue/archive) | 开放；无需机构账号 |
| dsh | Digital Scholarship in the Humanities | journal | Crossref元数据，非完整目录 | [官方入口](https://academic.oup.com/dsh) | 部分开放；非OA全文需机构订阅 |
| ijdh | International Journal of Digital Humanities | journal | Crossref元数据，非完整目录 | [官方入口](https://link.springer.com/journal/42803) | 部分开放；非OA全文需机构订阅 |
| ijhac | International Journal of Humanities and Arts Computing | journal | Crossref元数据，非完整目录 | [官方入口](https://www.euppublishing.com/loi/ijhac) | 部分开放；非OA全文需机构订阅 |
| dhq | Digital Humanities Quarterly | journal | Crossref元数据，非完整目录 | [官方入口](https://dhq.digitalhumanities.org/) | 开放；无需机构账号 |
| jtei | Journal of the Text Encoding Initiative | journal | Crossref元数据，非完整目录 | [官方入口](https://journals.openedition.org/jtei/) | 开放；无需机构账号 |
| jdh | Journal of Digital History | journal | 官方入口登记；未启用自动拆篇 | [官方入口](https://journalofdigitalhistory.org/en/articles) | 开放；无需机构账号 |

## 网络与机构访问（适用于不同高校、科研机构和图书馆）

- 全部来源的网络状态标为 `unknown`：未在中国大陆无代理网络逐站实测。不要把DNS错误、403、412、429、学校没有订购或登录失效统一归为“需要挂VPN”。
- 境外网络代理解决网络连通问题；机构VPN或图书馆代理解决校外机构资源访问，两者作用不同。工具沿用requests的标准代理环境变量，来源清单不包含任何用户代理地址、密码或令牌。
- 会议开放档案、DHQ、jTEI与JDH的公开内容一般无需学校账号；具体文件仍须以原站许可为准。登录按钮存在不表示阅读必须登录。
- DSH、IJDH、IJHAC的公开题录可先采集；非开放全文需机构订阅，访问权限取决于所属高校、科研机构或图书馆购买的具体期刊和年份；机构认证成功也不代表该机构订购了全部内容。未核实任何特定机构的订阅，不作全文可用保证。

可按以下顺序选择访问方式，不预设用户属于某所学校：

1. **开放获取**：直接访问官方全文或官方会议档案，通常无需机构账号。
2. **出版商机构登录**：在出版商页面选择 Institutional login / Access through your institution，搜索自己所属高校、科研机构或图书馆，按其支持的 Shibboleth、OpenAthens 等方式认证。参见 [Oxford 官方说明](https://academic.oup.com/pages/get-help-with-access/institutional-access)、[Springer Nature 官方说明](https://support.springernature.com/en/support/solutions/articles/6000079271-access-content-that-your-institution-subscribes-to)。
3. **中国大陆参与机构的 CARSI**：通过 [CARSI入口](https://ds.carsi.edu.cn/)选择本人所属机构；只适用于机构与资源均支持的情况。[CARSI官方常见问题](https://www.carsi.edu.cn/faq.html)。
4. **校园网、图书馆代理或机构VPN**：按所属机构图书馆的校外访问指南操作；不统一填写某一学校的VPN地址，也不假定必须使用VPN。
5. **机构未订购**：向所属图书馆咨询文献传递/馆际互借，或查找作者公开稿。工具不保存机构账号密码、不自动登录。

以上是机构资源访问路径；境外网络代理仅涉及连通性。来源的网络状态仍为待实测，不能由账号提示、HTTP 403或DNS失败推断必须使用境外代理。

## 稳定渠道与依据

- [Anthology官方说明](https://anthology.ach.org/about/)：开放会议论文档案。CHR、Humanistica、DHTech按各自卷分开，不把所有卷统称ACH年会。
- [DHNB出版说明](https://journals.uio.no/dhnbpub/about)：开放出版、OJS平台及PKP保存；[档案](https://journals.uio.no/dhnbpub/issue/archive)。
- [ADHO出版协议](https://adho.org/conference/conference-protocol/)：摘要集以PDF/XML发布并归档于开放存储库。2026年有修订版本；应记录具体版本，不猜新届记录号。
- [Zenodo API](https://developers.zenodo.org/)及[开放API原则](https://about.zenodo.org/principles/)：可做后续元数据与版本发现。当前只登记已核实记录，尚未实现摘要集拆篇。
- [Crossref API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)：无需注册，按ISSN查询；元数据仅限出版方提交内容。
- [DHQ官方XML仓库](https://github.com/Digital-Humanities-Quarterly/dhq-journal)与[DHd年度XML/CSV](https://github.com/DHd-Verband/DHd-Abstracts-2025)：后续结构化采集入口，不代表本次已有XML拆篇适配器。
- [CEUR-WS](https://ceur-ws.org/)可追溯早期CHR论文集，须由会议官方链接定位具体卷；本次不自动遍历或镜像整站。

## 数据与Zotero

单篇保留DOI、原文链接、摘要、作者、出版日期与会议届次显示文本，访问条件写入sourceNote。缺失摘要不生成。itemType新增conferencePaper支持；旧数据默认journalArticle。海外来源未单独映射Collection时沿用现有根Collection路径，不自动创建目录。

## 验证记录

- 271项离线测试通过，其中14项为新增海外来源测试；测试页面为人工最小样例，不冒充线上实抓。
- Ruff全量检查通过。
- 实时终端预览测试：Anthology域名DNS解析失败；未覆盖用户待筛数据，也未认定该站必须使用VPN。
- GitHub连接器可读取项目；网页检索可核实官方页面，但这不证明终端适配器可实时访问同一来源。
- MCP新增list_overseas_sources（只读）与capture_overseas_source（默认dryRun=True）。实际安装环境的外网连通与逐站实抓仍待验证。
