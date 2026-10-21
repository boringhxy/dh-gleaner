# 文档索引

本目录面向使用者与贡献者，说明这个工具怎么工作、数据长什么样、如何扩展。

| 文档 | 内容 |
|------|------|
| [workflow.md](workflow.md) | 四类抓取任务、筛选与导入流程、异常处理 |
| [data-format.md](data-format.md) | `Article` / `IssueInfo` 数据模型与各数据文件的格式 |
| [sources.md](sources.md) | 已支持的期刊、六种解析器、新增期刊的步骤 |
| [quality-and-safety.md](quality-and-safety.md) | 抓取质量校验规则、旧清单保护、安全与合规边界 |
| [zotero.md](zotero.md) | Zotero 集成：Collection 策略、字段映射、PDF 附件、错误处理 |
| [mcp.md](mcp.md) | MCP 工具参考：14 个工具的参数与返回结构 |
| [development.md](development.md) | 开发环境、测试要求、冒烟测试与发布前检查 |

根目录的 [README](../README.md) 讲「怎么用」，本目录讲「为什么这样设计、出问题看哪里」。

## 一句话概括设计

抓取与导入被刻意分开：抓取只负责产出清单，导入只负责把使用者明确选中的条目写进 Zotero。两者之间由 `data/pending.json` 与人工筛选环节连接。任何让这两端耦合的改动，都应当先讨论。
