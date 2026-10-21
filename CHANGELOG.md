# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的组织方式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **散篇 harvest 流程**：在「按期次」「按栏目」之外新增第三种采集模式，面向没有常设数字人文栏目、DH 内容散落在各栏目且当期目录页不稳定的图情/信息刊。按年枚举全年全目录 → DH 关键词筛 → 落 `pending.json`/`review.md`，`screen`/`import` 下游照常可用。命令行 `dhgleaner harvest --year YYYY [--journal X] [--all-catalog] [--no-abstracts] [--dedupe] [--dry-run]`，MCP 工具 `harvest_year`（默认 `dryRun=true`）。
- **三个 harvest 解析器**：`founder`（方正 rc-pub 开放 JSON API，内联中文摘要）、`journalx`（.NET aspx，`issue_list.aspx` 按季枚举 + `view_abstract` 逐篇抓详情）、`magtech` 过刊库（枚举 `volumn_N.shtml`，自动识别 `ul.lunwen`/`div.dqml`/经典 `noselectrow` 三种皮肤）。`BaseParser` 增 `supportsHarvest` 与 `harvestYear(year)`。
- **DH 关键词双表打标**（`dhgleaner/keywords.py`，capture 与 harvest 共用）：给每篇文章打 `dhMatched`/`histAiMatched` 双标签。判定口径——命中数字人文领域词，或历史学+AI 共现（历史词与计算方法词各≥1）；**计算方法词不单独算 DH**，以压住图情刊里「AI in LIS」论文带来的噪声。刻意排除「历史/古代/传统/文化/档案/记忆」等陷阱泛词，英文缩写大小写敏感匹配。
- **7 本散篇期刊**入默认配置（现代情报、情报科学、中国图书馆学报、国家图书馆学刊、数字图书馆论坛、图书情报知识、信息资源管理学报），标 `harvestOnly: true`：只进 harvest 轮转，被 `capture --all-journals` 与 `doctor --network` 跳过，用 `capture` 抓当期会被拒绝并提示改用 `harvest`（除非显式给 `--url`）。
- `Article` 增 `keywords`/`dhMatched`/`histAiMatched` 字段；`http_util` 增 `fetchJson`（与 `fetchHtml` 同套 401/403/412 拦截与重试语义）；新增 `textutil`（文本清洗 + 前置条目识别）。
- 离线测试 `tests/test_harvest.py`（关键词打标、前置条目过滤、三皮肤解析、harvest 过滤，全部用桩不发网络请求）。
- **反馈入口**：`.github/ISSUE_TEMPLATE/` 下三份 issue 表单——Bug 报告（索要 `dhgleaner doctor` 输出与 `data/last_capture_status.json`）、新增期刊源（索要免登录可访问的真实目录页 URL、站点平台、DH 内容分布以判定走 capture / capture-channel / harvest）、使用咨询；外加 `config.yml` 把安全问题导流到 SECURITY.md 的邮件渠道。另加 `.github/PULL_REQUEST_TEMPLATE.md`，把 CONTRIBUTING.md 的红线与提交前检查做成勾选清单。三份表单都强制确认「未粘贴 API Key」。

### 变更

- **MCP 服务端**工具数 13 → 14（写本地组新增 `harvest_year`）；`list_journals` 返回增加 `harvestOnly` 字段。
- 抓取质量校验对 `captureType="harvest"` 跳过「year==0」误抓判定（散篇清单本就没有单一期次）。

### 修复

- **CI 恢复绿灯**：`dhgleaner/mcp/tools_capture.py` 的 import 块触发 ruff `I001`（未排序），导致 harvest 那次提交的 8 个测试矩阵格子全部挂在 Lint 步骤、只有 build 任务通过。`captureHarvest` 原本被单独拆成一个 `from ..service import` 块，现与其余无别名导入合并；带别名的 `captureIssue as _captureIssue` 按 ruff isort 规则仍需独立成块（别名 `_captureIssue` 的排序位置与原导入名不同，合并会改变顺序语义）。纯 import 整理，无行为改动。
- **`doctor` 文案对齐新的安装方式**：依赖缺失时原本提示「请重新安装本包（`pip install -e .`）」，但 `-e` 是开发模式，与 README 改推 pipx / uv 之后自相矛盾；现改为指向 README「安装」章节，不再硬编码某一种安装方式的命令。另一处自检项标签由「配置模板（复制它来填密钥）」改为「配置模板（`dhgleaner init` 会替你写入凭据）」——pipx / uv 安装下模板深埋在 site-packages，让使用者去那儿复制并不现实，而 `init` 本来就是更好的路径（`getpass` 不回显、存完即测连接、权限 0600、覆盖前自动 `.bak`）。模板路径仍照常显示，只是不再暗示使用者去复制它。

### 文档

- **安装方式补齐免 clone 路径**：README 与 README.en.md 都改为推荐 `pipx install "dh-gleaner[mcp] @ git+https://..."` 与 `uv tool install`，并说明 `-e` 只用于改代码、git 源升级遇到 pip 缓存时用 `--force` / `--reinstall`。此前只有 `git clone` + venv + `pip install -e .` 一条路，对不打算改代码的使用者并不合适。
- **MCP 接入补两个实际会踩的坑**：客户端通常不继承 shell PATH（裸命令名会报找不到，改用 `command -v dhgleaner-mcp` 得到的绝对路径），以及客户端工作目录与命令行不同导致读到不同数据目录（`--data-dir` 对 MCP 无效，需在客户端配置里给 `DHGLEANER_DATA_DIR`）。`docs/mcp.md` 同步。
- **README.en.md 追平中文版**：补上此前完全缺失的 harvest 章节（含 DH 关键词双表判定口径）、Capture 表的 harvest 行、以及 7 本 `harvestOnly` 期刊表——英文版原本只列 6 本期刊，国际读者看不到 harvest 这条链路。
- **Zotero 凭据配置改为以 `dhgleaner init` 为主**：原文写「把仓库里的 `config.local.example.json` 复制成 `config.local.json`」，但 pipx / uv 安装下并不存在「仓库」；改为先给交互式 `init`，手动配置则说明写进数据目录下的 `config.local.json`，并指出 `dhgleaner doctor` 会打印确切路径。
- README 新增「反馈与求助」章节（中英对照），列清三类 issue、安全上报渠道、报 bug 时该附的两样东西，以及不会被接受的需求类型。
- harvest 命令示例由行内注释改为参数表：行内 `#` 注释在未开启 `interactive_comments` 的 zsh 里会被当成命令参数，整块粘贴会失败。

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
