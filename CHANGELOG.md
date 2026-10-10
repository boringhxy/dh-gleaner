# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的组织方式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

暂无。

## [0.1.0] - 2026-10-10

首个公开版本。核心契约是 **先筛选、后导入**：捕获阶段只生成清单，只有使用者明确选中的文章才会写入 Zotero。

### 新增

- **命令行工具 `dhgleaner`**，十个子命令：`doctor`、`capture`、`capture-channel`、`review`、`abstract`、`export-review`、`screen`、`import`、`init`、`init-collections`。
- **三种抓取模式**：按期次、按栏目跨期全量、按手动目录页 URL。
- **筛选流程**：按编号选择、按题名匹配并确认、导出 Excel 勾选、筛选篮逐步收集。
- **Zotero 集成**：通过 Web API 读写，支持复用既有 Collection、按刊物映射目录、导入报告。
- **PDF 降级**：下载、校验并挂载；失败或被拦截时降级为记录链接与原因，不阻断条目导入。
- **抓取质量校验**：识别导航页、广告页、重复标题、期次解析异常等情形，标记为 `suspect` 且不覆盖旧清单。
- **MCP 服务端**，暴露 13 个工具（8 只读 / 4 写本地 / 1 写 Zotero）。写 Zotero 的工具默认拒绝，需要同时给出 `confirm=true` 与 `dryRun=false`。
- **数据目录四级解析**：`--data-dir` > `DHGLEANER_DATA_DIR` > 当前目录 legacy 布局 > `~/.dhgleaner`。
- **`dhgleaner init` 初始化向导**：交互式录入 Zotero 凭据 → 测试连接 → 可选补齐 Collection 目录 → 环境自检。非交互环境（MCP、CI、管道）自动降级为打印手动配置步骤，不阻塞提问。
- **`dhgleaner init-collections` 显式建目录命令**：默认只读预览各刊 Collection 缺哪些层级，加 `--yes` 才真正写入 Zotero；可用 `--journal` 限定单刊。导入流程本身仍不会擅自建目录。
- **可安装包**：`pip install -e .` 后可在任意目录使用；另有 `[mcp]` 与 `[dev]` 两个可选依赖组。
- MIT 许可证，随附 `config.local.example.json` 凭据模板。

### 变更

- **默认配置单一真源**：移除仓库根与包内内容重复的 `config.json`，默认配置只保留 `dhgleaner/defaults/config.json` 一处（随 `dhgleaner` 包发布，CI 已校验 wheel 内含该文件）。运行时行为不变——`loadConfig()` 本就以包内默认为基线；如需个性化，仍可在数据目录放一个 `config.json` 覆盖，凭据依旧只写 `config.local.json`。

### 移除

- **发布窗口自动调度死代码**：删除从未接线的 `isInPublishWindow` 与 `captureAll` 的 `scheduleCfg` 分支，对齐产品「不做监控、由用户手动触发」的定位；设计文档相应加存档说明。

### 修复

- **`state.json` 原子写入**：改为「临时文件 + fsync + `os.replace`」落盘，进程中途被杀不再留下半截 JSON。
- **`state.json` 损坏不再静默清空**：解析失败时把坏文件另存为 `.corrupt-<时间戳>` 并 `log.error`，而非重置为空。此前静默重置会让「已处理」记录消失，导致下次运行把老文章当新文章重复导入 Zotero。
- **Zotero 查重翻页**：`checkDuplicate` 改用 `everything()` 翻页扫描并归一化比较标题（容忍全半角/引号/标点差异），命中项超过单页 `limit` 时不再漏判；同时设扫描上限，避免病态宽命中把整库拉下来。
- **筛选篮容错**：`loadBasket` 遇到脏/损坏 JSON（非数字编号、非对象顶层结构）时降级为空篮或陈旧篮，不再抛异常崩溃。
- **类型注解纠偏**：解析器 `_parseOneArticle` 标注为 `Optional[Article]`（实际会返回 `None`），`Article.authors` 标注为 `list[str]`。
- 预检中止的导入不再改动本地文件。此前实现会无条件重写 `pending.json` 与 `review.md`，导致「凭据未配置」这类纯失败也会刷新捕获时间，并把已标记为 `presented` 的文章打回 `selected`，使已经看过的文献重新出现在待筛清单里。现在中止时一个字都不落盘，中止原因仍由返回值携带。
- `mcp` 依赖下界由 `1.2.0` 修正为 `2.0.0`：代码使用的 `mcp.server.mcpserver` 模块自 2.0.0 起才存在。

### 安全

- **凭据落盘收紧**：`saveCredentials` 只写 `config.local.json`（`.gitignore` 已忽略），权限设为 `0600`，覆盖前自动备份为 `.bak-<时间戳>`；录入时 API key 走 `getpass` 不回显。

### 文档

- README 快速开始改为「先展示无需凭据即可抓取筛选，再引导 `init` 配置 Zotero」；新增 `init` / `init-collections` 命令参考。
- 开发安装由 `.[dev]` 改为 `.[dev,mcp]`；未装 `mcp` 时自动跳过 server 注册校验，保证 `.[dev]` 也能跑通测试。

### 已知限制

- `preview_import` 对无法解析的编号会返回 `status="empty"`，尚未与 `get_article_abstract` 的 `invalid_input` 对齐。
- 抓取失败时命令行的退出码仍为 0。
- `state.json` 没有归档或裁剪机制，长期使用会持续增长。

[Unreleased]: https://github.com/boringhxy/dh-gleaner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/boringhxy/dh-gleaner/releases/tag/v0.1.0
