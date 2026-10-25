# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的组织方式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **散篇 harvest 流程**：在「按期次」「按栏目」之外新增第三种采集模式，面向没有常设数字人文栏目、DH 内容散落在各栏目且当期目录页不稳定的图情/信息刊。按年枚举全年全目录 → DH 关键词筛 → 落 `pending.json`/`review.md`，`screen`/`import` 下游照常可用。命令行 `dhgleaner harvest --year YYYY [--journal X] [--all-catalog] [--no-abstracts] [--dedupe] [--dry-run]`，MCP 工具 `harvest_year`（默认 `dryRun=true`）。
- **三个 harvest 解析器**：`founder`（方正 rc-pub 开放 JSON API，内联中文摘要）、`journalx`（.NET aspx，`issue_list.aspx` 按季枚举 + `view_abstract` 逐篇抓详情）、`magtech` 过刊库（枚举 `volumn_N.shtml`，自动识别 `ul.lunwen`/`div.dqml`/经典 `noselectrow` 三种皮肤）。`BaseParser` 增 `supportsHarvest` 与 `harvestYear(year)`。
- **DH 关键词双表打标**（`dhgleaner/keywords.py`，capture 与 harvest 共用）：给每篇文章打 `dhMatched`/`histAiMatched` 双标签。判定口径——命中数字人文领域词，或历史学+AI 共现（历史词与计算方法词各≥1）；**计算方法词不单独算 DH**，以压住图情刊里「AI in LIS」论文带来的噪声。刻意排除「历史/古代/传统/文化/档案/记忆」等陷阱泛词，英文缩写大小写敏感匹配。
- **7 本散篇期刊**入默认配置（现代情报、情报科学、中国图书馆学报、国家图书馆学刊、数字图书馆论坛、图书情报知识、信息资源管理学报），标 `harvestOnly: true`：只进 harvest 轮转，被 `capture --all-journals` 与 `doctor --network` 跳过，用 `capture` 抓当期会被拒绝并提示改用 `harvest`（除非显式给 `--url`）。
- `Article` 增 `keywords`/`dhMatched`/`histAiMatched` 字段；`http_util` 增 `fetchJson`（与 `fetchHtml` 同套 401/403/412 拦截与重试语义）；新增 `textutil`（文本清洗 + 前置条目识别）。
- **`dhgleaner --version`**：打印 `dh-gleaner <版本号>`。此前没有任何途径确认使用者装的是哪一版，而 bug 模板要的 `doctor` 输出里也没有版本——同一份代码在不同 commit 上行为可能差很多。Bug 模板相应新增必填的「版本」输入框。
- **版本号收敛到一处**：`pyproject.toml` 改用 hatchling 的 dynamic version 从 `dhgleaner/__init__.py` 的 `__version__` 读取。此前两处各写死 `0.1.0`，发版时漏改一处就会打出两个不同版本。`docs/development.md` 的发布前检查补上版本一致性一条。
- 离线测试 `tests/test_harvest.py`（关键词打标、前置条目过滤、三皮肤解析、harvest 过滤，全部用桩不发网络请求）。
- **抓取命令按质量返回退出码**：`capture` / `capture-channel` / `harvest` 成功 0、`failed` 1、`suspect` 3。此前无论抓到什么都是 0，cron 或 CI 包一层脚本也判断不出「这次算不算数」，只能去解析终端中文。`3` 而不是 `2`——`2` 已被 argparse 的参数错误占用，混用就分不清「命令写错了」和「站点没给数据」。走 `SystemExit` 而非返回值，因为 `dhgleaner`、`python -m dhgleaner`、`python main.py` 三个入口都是直接调 `main()`，返回值会被丢掉。
- **反馈入口**：`.github/ISSUE_TEMPLATE/` 下三份 issue 表单——Bug 报告（索要 `dhgleaner doctor` 输出与 `data/last_capture_status.json`）、新增期刊源（索要免登录可访问的真实目录页 URL、站点平台、DH 内容分布以判定走 capture / capture-channel / harvest）、使用咨询；外加 `config.yml` 把安全问题导流到 SECURITY.md 的邮件渠道。另加 `.github/PULL_REQUEST_TEMPLATE.md`，把 CONTRIBUTING.md 的红线与提交前检查做成勾选清单。三份表单都强制确认「未粘贴 API Key」。
- **发现层新增两个 tier1 公告源**（实测 2026-10-25）：《情报科学》与《国家图书馆学刊》的 CNKI 采编平台首页（`cnki_cbpt_current`）无需验证码即可宣告当前期——分别已宣告 2026 年第 7 期、第 9 期，而官网逐篇页当时停在第 5 期、第 4 期；discover 现在能报出「官方页落后 N 期」。其余各刊实测无公开可用的更快公告源（CBPT 首页挡验证码、方正发布平台仅《现代情报》入驻、DHCN 分类按学科不按刊；另实测 openvbk 域名已解不开、万方期刊页纯 JS 渲染、fabiao/istpei 类镜像为无结构 SEO 壳）。
- **发现源「路子」提示（hints）**：原则是机器路径优先，人工只作兜底且必须自带可操作路径。发现源与刊级配置各增 `hints` 列表（`SourceResult.hints`/`JournalDiscovery.hints`，进 `toDict` 供 MCP 消费）；当源处于 ✍/⛔/✗/· 状态、或整刊无 frontier 时，CLI 在明细与「下一步」下逐条列出（公众号名、官网公告页、record-url 用法等），`discover --no-record` 同样可见。

### 变更

- **改为采纳 `uv.lock`（推翻 2026-10 早期「不加 lockfile」的记录）**：当时的理由——pipx/uv tool 不读 lock、常更新的包会腐烂——依然成立，端到端安装路径也仍由 build job 的 sdist/wheel 冒烟覆盖；但「在仓库里开发」这一条路径此前完全不受约束：今天测试绿、明天重装环境后依赖悄悄换版本，排查要猜是代码还是依赖。CI 测试作业改为 `uv venv --python <矩阵版本>` + `uv sync --locked`：pyproject 与 lock 不同步时直接失败，腐烂担忧由 CI 强制消掉。跨版本实测（2026-10-25）：`uv sync --locked` 在 Python 3.10 与 3.13 的独立环境均通过。
- **MCP 服务端**工具数 13 → 14（写本地组新增 `harvest_year`）；`list_journals` 返回增加 `harvestOnly` 字段。
- **抓取更克制**：重试间隔从固定 `retryInterval` 改为指数退避（上限 300 秒），站点返回 `Retry-After` 时优先听站点的；`capture-channel` 的逐页请求之间接入 `harvestDelay` 限速（此前只有 harvest 路径限速）；栏目分页数加 `maxChannelPages` 硬上限（默认 50）——「共 N 页」是用正则从页面文本抠的，抠错一位数就会变成上万个请求，触顶时记为失败而非静默少给清单。补 `tests/test_fetch_policy.py` 11 个离线用例。
- 抓取质量校验对 `captureType="harvest"` 跳过「year==0」误抓判定（散篇清单本就没有单一期次）。
- **依赖加上界**：四条运行时依赖与 `mcp` extra 从只写下界改为封到下一个 major（`requests<3`、`beautifulsoup4<5`、`lxml<7`、`pyzotero<2`、`mcp<3`）。开区间意味着某天 `pipx install --force` 会静默升到一个没测过的接口，而 `mcp` 已经证明这类 breaking major 真的会发生（1.x → 2.0.0 直接换掉 `mcp.server` 布局）。上界刻意容得下当前验证过的组合（requests 2.34 / bs4 4.15 / lxml 6.1 / pyzotero 1.16 / mcp 2.3），不把已经能装的人锁在门外。不加 lockfile：本项目推荐 `git+https` 源安装，`pipx` / `uv tool install` 都不读 `uv.lock`，它只服务「在仓库里开发」一种场景，收益抵不上常更新的成本。
- **CI 增加 Windows**：矩阵从 ubuntu + macOS 扩到三平台 × 4 个 Python 版本。此前 Windows 完全没测过，但安装方式（pipx / uv）和 `requires-python >=3.10` 都没有排除它。配套修掉两处只在 POSIX 成立的前提：`0o600` 权限断言在非 POSIX 平台跳过（NTFS 不保存 POSIX 权限位，`os.chmod` 在 `service.py` 里本来就是 `suppress(OSError)`），终端日志流在 Python 3.7+ 上重配为 UTF-8（英文区 Windows 默认 cp1252，中文日志行会触发 `UnicodeEncodeError`，logging 会把它吞成「--- Logging error ---」让终端一片空白）。第一轮 CI 也照出两处：`test_agent.py` 里直接调 `cmdExportReview` / `cmdImport` 的用例绕过了 `main()`，因而拿不到那步 UTF-8 修正，两个改用 `redirect_stdout` 接走输出并加了断言——生产入口只走 `main()`（MCP 不打印），所以修的是测试而不是往每个 `cmd*` 里塞 `forceUtf8`。
- **删掉仓库根目录的重复密钥模板**：`config.local.example.json` 在根目录和 `dhgleaner/defaults/` 各有一份、逐字节相同，但代码只读包内那份（`paths.py` 的 `configTemplatePath`），CI 校验的也是包内那份。两份必然漂移，还会让人纠结该改哪一份。根副本连同 sdist `include` 里的引用一并删除。
- **测试样例集中到 `tests/samples.py`**：`SAMPLE_JOURNY3` / `SAMPLE_CNKI` 与解析器用的 `HTTP_CFG` 原本在 `test_parsers.py` 和 `test_agent.py` 各存一份逐字相同的副本，长 UA 串还有第三份在 `test_harvest.py`。样例一改就两处不同步，两个文件会给出互相矛盾的「预期」。
- **CI 的三个 action 升到最新主版本**：`actions/checkout@v4` 声明的是 Node.js 20，GitHub 已弃用该运行时（每次运行都刷一条 annotation，且 `ubuntu-latest` 马上要迁到 Ubuntu 26），checkout v4 会先被强制跑在 Node 24 上。现升到 `checkout@v7` / `setup-python@v7` / `upload-artifact@v7`（三者都是 Node 24 运行时）。工作流里这三个 action 除 `python-version` / `name`+`path` 外没有别的入参，跨主版本没有可破的接口；`upload-artifact` 要求同一工作流内产物名唯一，本仓库只有一个 `dist`。

### 修复

- **抓取质量闸门改为逐刊判定**：`capture --all-journals` 过去把全部期刊的文章数加总后只按第一刊的期次信息判定质量（`results[0][1]`），一刊抓崩、其余正常时仍报 `success` 并覆盖上一次的 `pending.json`——正好违背「失败绝不覆盖旧清单」的承诺。现由 `assessBatchQuality` 逐刊评估，任一刊异常即整批 `suspect`，全部失败才 `failed`；合法的「空」（dedupe 命中已处理期次、harvest 筛完无命中）不再拖垮整批判定。补 `tests/test_capture_gate.py` 14 个用例，含「把 `_finishCapture` 的判定反过来、套件仍能全绿」这两条过去无人看守的落盘保护。
- **抓取失败原因上抛，并区分「拒绝自动化」与「临时故障」**：`captureJournal` / `captureChannel` / `harvestJournal` 现在多返回一个 `CaptureFailure(journal, stage, kind, detail)`，一路带到 CLI 输出、MCP 结果与 `data/last_capture_status.json`。CLI 把 `kind="blocked"`（401/403/412）单独列为「拒绝自动化访问，重试无用」，与可重试的临时故障分开——此前两者都只躺在日志里，而 bug 模板恰恰要求使用者附上状态文件。
- **《图书馆杂志》的配置与文档不再声称能自动抓取**：官网反爬前置检查对普通 HTTP 请求**稳定**返回 412，但 `pdfNote` 写的是「偶发」，且 `historyUrlTemplate` 含 `{volume}` 却没配 `volumeYearBase`/`volumeBase`，按年期定位过刊必然失败却只报「未找到该期」。现在三处文档（README 中英、`docs/sources.md`）都标明需手动 `--url`；缺卷号时的报错会直接指出缺 `volumeYearBase`/`volumeBase` 并给出 `--url` 出路。真实卷号未凭空填入——412 挡住就无法核实，编造只会静默生成错 URL。
- **乱码检测进质量闸门**：标题或摘要含解码替换符 U+FFFD 时判 `suspect`。站点声明错编码、或 `apparent_encoding` 猜错时整页中文会成片变成 U+FFFD，过去这种清单看着「有文章、标题不重复」能直接判 `success` 覆盖旧清单。
- **导航词黑名单合到一处**（`dhgleaner/textutil.py` 的 `isNavigationTitle` / `isBlacklistedTitle`）：`capture` 的质量闸门与 `generic_html` 解析器原本各维护一份词表，闸门那份不含「过刊浏览 / 在线投稿 / 关于我们 / 广告合作」，整页抓成导航时仍能报 `success` 并覆盖旧清单。合并时顺带收紧拉丁词——`Journal` / `More` 这类改为整条相等才算，避免《Journal of Digital Humanities 的引文分析》被误判。
- **CI 恢复绿灯**：`dhgleaner/mcp/tools_capture.py` 的 import 块触发 ruff `I001`（未排序），导致 harvest 那次提交的 8 个测试矩阵格子全部挂在 Lint 步骤、只有 build 任务通过。`captureHarvest` 原本被单独拆成一个 `from ..service import` 块，现与其余无别名导入合并；带别名的 `captureIssue as _captureIssue` 按 ruff isort 规则仍需独立成块（别名 `_captureIssue` 的排序位置与原导入名不同，合并会改变顺序语义）。纯 import 整理，无行为改动。
- **`journalx` 不再按固定行号取作者与年期页**：`_rows` 原本取 `trs[i+1]` 当作者行、再在 `(i+1, i+2, i+3)` 这个固定窗口里找「年, 卷(期): 页码」行，依赖的是「每篇恰好 3 个 `<tr>`」这个页面约定。站点多插一行（作者单位、DOI）就会读到下一篇文章的行，把别人的卷期页挂到这篇文章上。现改为从题名行往后扫、遇到下一个题名行即停，跳过嵌套表格的包裹行，并按行的内容而不是位置判定它是作者行还是年期页行；年期页行不会被当成作者，缺失作者行也不会误吃下一篇的年期页。**「下一个题名行」必须和「取题名」用同一口径**：实测《中国图书馆学报》真实目录页时发现，年期页行里也挂着一个 `view_abstract.aspx?file_no=` 链接（那个「摘要」），只按 href 判断就会停在年期页行上、整刊的卷号与页码全丢；`tests/test_harvest.py` 把这一条钉成了用例。
- **`publishDate` 规范化**：`journy3` 与 `magtech` 的日期捕获组是宽松的 `[\d-]+`，`2026-6-2`、`--`、`2026-06-28-abcd` 都能匹配上，然后被 `zotero_client` 原样写进条目的 `date` 字段。现在过一道 `normalizeDate`：认 `2026-06-28` / `2026-06` / `2026` 及 `.` `/` 分隔的写法并补零成 ISO，认不出来就留空串——`date` 自然回退到年份，比写进一个 Zotero 解析不出的脏值好。`docs/data-format.md` 相应说明字段保证是 ISO 或空。
- **`journy3` 不再写死站点地址**：`BASE_URL` 是类里的常量，`articleUrl` 与 `pdfUrl` 都从它拼，`getParser` 也不给它传 `baseUrl`（同文件的 magtech / journalx 都传）。结果《数字人文研究》换域名或转 https 必须改代码，配置里新增同平台期刊也没法复用这个解析器。现在按配置 `url` 走，包内默认值兜底，现有配置行为不变。
- **《图书馆杂志》的 412 范围写小了，栏目抓取其实一直可用**：上一轮修配置时把「反爬前置检查」记成了整站行为，README 中英、`docs/sources.md`、包内 `pdfNote` 于是一致写着「期次与栏目抓取目前都无法自动完成」。本次按端点复测：`current.shtml` 仍是 412（期次抓取确实走不通），但栏目页 `showChannelArticle.do` 与过刊索引 `showOldVolumn.do` 用同样的普通请求返回 200，单页解析出 40 篇、合并分页后 67 篇，每篇的 `issueDisplay` 与起止页都齐全——`capture-channel --journal 图书馆杂志 --channel 数字人文` 是本工具唯一一条能直接跑的栏目用例，却被文档说成不可用。四处文案按端点改口径，红线不变：依旧不绕过该检查，抓单期仍只能 `--url`。补 `tests/test_fetch_policy.py` 一条离线用例，钉住「非 `magtech` 皮肤在发出任何请求之前就返回 `stage=unsupported`」，那正是新文案对读者复述的报错。
- **`doctor` 文案对齐新的安装方式**：依赖缺失时原本提示「请重新安装本包（`pip install -e .`）」，但 `-e` 是开发模式，与 README 改推 pipx / uv 之后自相矛盾；现改为指向 README「安装」章节，不再硬编码某一种安装方式的命令。另一处自检项标签由「配置模板（复制它来填密钥）」改为「配置模板（`dhgleaner init` 会替你写入凭据）」——pipx / uv 安装下模板深埋在 site-packages，让使用者去那儿复制并不现实，而 `init` 本来就是更好的路径（`getpass` 不回显、存完即测连接、权限 0600、覆盖前自动 `.bak`）。模板路径仍照常显示，只是不再暗示使用者去复制它。
- **`import --dry-run` 在任何导入路径下都真的只读**：预览分支过去写成 `if args.spreadsheet and args.dry_run`，只在带表格时生效；`import --all --dry-run`、`import --selection "1" --dry-run` 会穿过判断直接执行导入——建条目、下 PDF、把文章标成已导入、覆写 `pending.json`。使用者的意图明确写成了「我只看看」，拿到的却是不可逆的外部写入。现在 `--dry-run` 提前拦住 `STATUS_OK` 与 `STATUS_SKIP_ALL` 两种结果，连「本批全部跳过」的标记动作也不执行，只把将要发生什么打印出来。帮助文本随之从「配合 --spreadsheet」改为适用于所有路径。
- **`--selection` 不再接受空值**：`SKIP_TOKENS` 里有空串，于是 `dhgleaner import --selection "$PICK"` 在变量没展开（或手滑写了 `""` / `无` / `null`）时等同于「都不要」：整张待筛清单被逐篇标成已处理、当期直接封口，之后 `capture --dedupe` 会永久跳过这一期，`pending.json` 同时被覆写——全程没有任何确认。MCP 侧同类操作早就要求 `confirm=true`，CLI 这条却无人看守。现在空 / 纯空白的 `--selection` 报「不能为空」并不碰任何文件；`都不要` 仍照旧可用，README 中英与 `docs/workflow.md` 补了这句口径。
- **部分清单不再把整期标成「已处理」**：`resolveSkipAll` 与 `importer._markCompleteIssues` 判的是「这批同刊同期的文章都处理过了」，而栏目抓取（`sourceType="channel"`）和散篇 harvest 交给它们的只是筛过的子集——子集全被跳过就等于宣布整期看完，`capture --dedupe` 从此再不抓这一期，期次里没进过清单的文章永久丢失。新增 `state.issueFullySeen()` 只认整期目录抓取（`sourceType="issue"`），补 `tests/test_selection.py` 用例：栏目来源的两篇 skip-all 后文章照旧标记跳过，但 `isIssueProcessed` 必须仍是 `False`。
- **栏目分页上限不再被 `changePage` 分支绕过**：`discoverChannelPageUrls` 有两条凑页数的路——「共 N 页」文本和 `onclick="changePage('N',...)"` 分页项，封顶却只写在第一条里。真实 Magtech 页面的分页项常按整站期次列出（实测 40 项），配上「每页 N 条」下拉框的写法，上限 50 形同虚设，一次栏目抓取能发出上百个请求。现在合并去重后的全集统一截到 `maxChannelPages`，并只在真的截断时打一条 warning。`tests/test_fetch_policy.py` 新增两条离线用例（40 个分页项 → 恰好 5 个 URL、`channelPagesTruncated` 记账）。
- **恰好等于分页上限的栏目不再被误判成触顶**：判定用的是 `len(pages) >= maxChannelPages`，于是「这个栏目正好有 50 页」这种完整清单也算触顶，`capture-channel` 报 `suspect` 并且不落盘——抓到了却什么都没留下，用户只看到一次失败。改为由解析器自己记 `channelPagesTruncated` 标志（只有真截断才置位），capture 读标志而不是数页数；补「5 页正好用满上限 → `failure is None` 且逐页限速走完」的端到端用例。
- **手工修复过的 `state.json` 不再在导入中途炸掉**：`_journalState` 假设每个刊对象都带齐 `processedArticles` / `processedArticleMeta` / `lastIssue` / `lastCheckAt` 四个键。而 state 损坏时的官方指引明确写着「可以从 `.corrupt-*` 备份里手工挑记录粘回来」——照着做的人粘一个只含文章列表的刊对象，就会在导入进行到一半时 `KeyError`：前几篇已经写进 Zotero，剩下的全断。现在改成逐字段 `setdefault` 补齐、类型不对的字段（刊值写成字符串、列表写成字典）一并纠正，补 `tests/test_state_atomicity.py` 用例覆盖两种缺法。
- **坏输入给的是错误提示，不是 traceback**：`--spreadsheet` 指到一个合法 zip 但不是 xlsx（改过后缀名的 `.zip`、Excel 抽风存的半截文件）时，`zf.read("xl/workbook.xml")` 抛 `KeyError`、XML 解析抛 `ParseError`，而调用方只捕 `SpreadsheetValidationError`，用户看到一整屏 traceback；编号单元格填 `inf` / `9e999` 时 `int(float(...))` 抛的是 `OverflowError`，同样漏网。题名文件是 Windows 记事本常见的 GBK 编码时，`read_text` 抛 `UnicodeDecodeError`。三处都补了转译，报「不是有效的 XLSX 筛选表，缺少 …」「筛选表内部 XML 已损坏…」「第 N 行编号不是数字…」「题名文件不是 UTF-8 编码…」。这三类崩溃都在写入之前，不会留下半截导入。
- **`generic_html` 抓 WordPress 式清单页：站点外壳不再进清单、栏目不再错位一格**：用 `capture --journal 中国数字人文 --url https://www.dhcn.cn/category/dhjournal/202504` 抓 DHCN 的《数字人文》某期页时，清单前 7 条全是站点导航（「数字人文专业发展联盟」「中国数字人文发展报告」「国内论文（元数据检索）」…）——它们都挂在 `li.menu-item` / `div.side-menu` / `div.site-header-inside` / `<nav>` 里，而 `titleKeywords` 恰好留着带「数字人文 / 数据」字样的这几条。同时「栏目」字段整体错位一格：每条自己的题名就是 `h2.entry-title`，`_nearestSection` 往前找到的第一个标题其实是**上一篇文章的题名**。现在解析器按结构排除外壳（标签名 `nav`/`footer`/`aside`，class 整词匹配——刻意不做子串匹配，否则 `entry-header` 会把真实条目一起杀掉），栏目只认「不带链接、且不是页面 h1 主标题」的标题；配置项 `containerSelectors` 命中时视为人工已认定容器内全是条目，不再叠加 `titleKeywords`，于是《数字人文》2025 年第 3 期从 3 篇升到 9 篇（原先「低资源条件下的西夏文OCR与机器翻译研究」这类不含关键词的题名被整篇丢掉）。补 `tests/test_parsers.py` 五条离线用例，覆盖外壳过滤、栏目不错位、可信容器免关键词、以及「栏目名本身不带链接」这一既有行为不被打断。
- **`init-collections` 不再把预检失败说成「都已就绪」**：每本期刊的预检行在出错时 `missing` 是空的，而收尾判断只看 `missing` 有没有内容，于是凭据填错（`400 Invalid user ID`，13 本全部出错）时终端照样打「✅ 目标期刊的 Collection 目录都已就绪，无需创建。」——表格里的「⚠️ 预检出错」被这句话当场推翻，使用者据此去跑 `import`，只会撞上「Collection 路径不存在」。现在范围内任一行出错就直接收尾：声明「查不到缺口不等于已就绪」、本次不写任何目录，并给出凭据修复入口。补 `tests/test_onboarding.py` 用例钉住「出错时不得调用 `ensureCollections`」。
- **`generic_html` 认得「第」字，期次不再退化成 `issue=0`**：期号正则写作 `(20\d{2})年\s*0*(\d{1,2})\s*期`，只接受紧贴数字的「期」字；DHCN 各期页的 h1 实际写作「《数字人文》2025年第4期」，带「第」就匹配不上——`year` 由同一串的另一条正则单独抠到、`issue` 落空成 0，清单和写进 Zotero 的条目都缺期号，`capture --dedupe` 记下的期次键也跟着错。现改为 `(20\d{2})年\s*第?\s*0*(\d{1,2})\s*期`，「2025年4期」「2025年 第4期」「2025年第04期」一并认下；补 `tests/test_parsers.py` 的 `testIssueNumberFromPageTitle`，用 DHCN 真实的 h1 写法钉住 `issue == 4`。
- **导入失败终于说清「为什么失败」，断连的写入会先回查再定性**：`createArticleItem` 原先把所有异常压成 `None`，`importArticle` 一律报「创建条目失败」；而 `POST /items` 抛 `Server disconnected without sending a response.` 时服务端**其实已经提交写入**——2026-10-23 实测：一条报「失败」的《数字人文》文章重跑变成「跳过（标题已存在）」并带回 key `H5DMUPHC`，使用者据此会以为没写进去、再导一遍。现在异常按报文分成 `connection` / `rejected` / `api` 三类（`classifyCreationFailure`；按报文判断而不 `isinstance(httpx.*)`——httpx 只是 pyzotero 的传递依赖，不该被本模块直接依赖）：`connection` 类先回查一次查重，查到就报「写入已完成，只是响应中断」并给出 key、不再留重跑的余地，查不到才报失败并说明「重跑一次，若报标题已存在说明其实写成了」；`rejected`（401/403/412/Invalid user ID）明说「重试无用，检查 webLibraryId 是否为数字 userID」；其余带上服务端原话。同类误归因还有一处：`locateJournalCollection` 把「目录列表请求失败」和「目录不存在」都返回 `None`，凭据填错时报告写满屏「Collection 路径不存在」，把人支去 Zotero 里手动新建 13 个目录——现在客户端记 `collectionReadError`，导入端优先报「无法读取 Zotero 目录」并指向 `dhgleaner init` / `doctor --zotero`。补 `tests/test_zotero_client.py` 的 `CreationFailureAttributionTests`（分类表、断连已写成、断连未写成、凭据被拒、服务端 `failed`）和 `CollectionReadErrorTests`（目录列表抛错要记下 `collectionReadError`、正常读完要清空它）共 7 个用例，加 `tests/test_import_isolation.py` 1 个（读目录失败不得说成路径不存在），共 8 个离线用例。
- **`import --selection` 与 `screen --add` 共用一个编号解析器**：`--selection` 原先只把逗号段逐个 `int()`，`"1-7"` 解析失败只打一条 `无法解析选择` 的 WARNING 就返回空列表，CLI 接着报「未选中任何文章」——同一种写法在 `screen --add` 那边好使，使用者按记熟的那条写，拿到的是静默零导入。现在两处都走 `parseIndexSpec`（`1,3-5`、中文逗号、顿号、分号都吃），解析不了时报 `invalid` 并说明支持的写法，编号越界则告知「当前清单共 N 条，有效编号 1-N」；`--selection` 帮助文本同步。补 `tests/test_selection.py` 两个新用例（`"1,3-5"` 区间可用、非法 token 不得降级成 empty），并在既有的越界用例里加断言钉住「当前清单共 N 条，有效编号 1-N」——原先只验「未选中任何文章」，越界提示怎么写都能过。

### 文档

- **安装方式补齐免 clone 路径**：README 与 README.en.md 都改为推荐 `pipx install "dh-gleaner[mcp] @ git+https://..."` 与 `uv tool install`，并说明 `-e` 只用于改代码、git 源升级遇到 pip 缓存时用 `--force` / `--reinstall`。此前只有 `git clone` + venv + `pip install -e .` 一条路，对不打算改代码的使用者并不合适。
- **MCP 接入补两个实际会踩的坑**：客户端通常不继承 shell PATH（裸命令名会报找不到，改用 `command -v dhgleaner-mcp` 得到的绝对路径），以及客户端工作目录与命令行不同导致读到不同数据目录（`--data-dir` 对 MCP 无效，需在客户端配置里给 `DHGLEANER_DATA_DIR`）。`docs/mcp.md` 同步。
- **README.en.md 追平中文版**：补上此前完全缺失的 harvest 章节（含 DH 关键词双表判定口径）、Capture 表的 harvest 行、以及 7 本 `harvestOnly` 期刊表——英文版原本只列 6 本期刊，国际读者看不到 harvest 这条链路。
- **Zotero 凭据配置改为以 `dhgleaner init` 为主**：原文写「把仓库里的 `config.local.example.json` 复制成 `config.local.json`」，但 pipx / uv 安装下并不存在「仓库」；改为先给交互式 `init`，手动配置则说明写进数据目录下的 `config.local.json`，并指出 `dhgleaner doctor` 会打印确切路径。
- README 新增「反馈与求助」章节（中英对照），列清三类 issue、安全上报渠道、报 bug 时该附的两样东西，以及不会被接受的需求类型。
- **`docs/quality-and-safety.md` 与代码对齐**：原文把「没有捕获到任何文章」列在 `suspect` 判定里，但代码返回的是 `failed`；现按 `suspect` / `failed` 分列，并补上「判定逐刊进行」、U+FFFD 检测、栏目分页触顶三条。新增「抓取节流」小节记录指数退避、401/403/412 不重试、`harvestDelay` 限速与 `maxChannelPages` 上限。`docs/mcp.md` 补上抓取类工具结果里的 `failures` / `blockedJournals` 两个逐刊字段。
- **README 质量校验章节追平实现**：中英两版都补上「判定逐刊进行」、U+FFFD 检测、栏目分页触顶三条 `suspect` 规则，以及新的「退出码」小节和 `data/last_capture_status.json` 里 `failures` 的 `stage` / `kind` 说明；`docs/quality-and-safety.md` 同步。
- **Bug 模板不再强制要求 `doctor` 输出**：原来这个字段是必填，但模板同时提供「安装 / 依赖」这一环节——命令装不上的人根本跑不出 `doctor`。改为选填并说明：跑不起来就贴安装报错。
- **README 代码块里的行内 `#` 注释清扫干净**：未开启 `interactive_comments` 的 zsh 会把 `#` 之后的内容当成命令参数，整块粘贴直接失败。此前只处理了初始化、自检与 harvest 三处，现在把中英两个 README 剩下的 41 行全部挪出代码块，说明改成代码块前的一句话或代码块后的列表。**中英两版同步修改**——只改一版会立刻重新分叉。
- harvest 命令示例由行内注释改为参数表：行内 `#` 注释在未开启 `interactive_comments` 的 zsh 里会被当成命令参数，整块粘贴会失败。
- **README 的「抓取」章节去掉一份重复且过期的命令表**：中英两版都是「五种抓取类型表」下面再挂一个 8 行代码块，同一批命令写两遍，而代码块里还留着《图书馆杂志》期次抓取这种已确认走不通的示例。现只保留表格（多带一列适用场景，并补上英文版漏掉的 `--all-journals` 一行），把 `capture-channel` 的成立前提（仅 `magtech` 皮肤、栏目地址来自 `channelSources` 或 `--url`）写成表后一段话。
- **`tests/helpers.py` 里没人用的 `FakeZotero` 删除**：各测试文件的假客户端是按「注入哪一种故障」分别写的（`test_agent.FakeZotero` 记调用次数、`test_import_isolation._UnreachableZotero` 直接抛错、`test_onboarding.FakeCollectionsZotero` 模拟目录树），合并反而丢掉这些差异；helpers 里那一份是唯一没有任何文件引用的，字段名还和其余几份都不同，留着只会被当成共享实现去改。
- **`main.py` 的地位写进贡献指南**：`CONTRIBUTING.md` 要求面向用户的文案统一用 `dhgleaner`，但根目录仍保留 `python main.py` 兼容入口、sdist 也照常打包它，贡献者无从判断它还算不算受支持。现写明：它是给改造前就在用 `python main.py` 的人留的兼容入口，不是文档口径，新脚本不要依赖它。
- **导入的编号写法与失败归因同步到文档**：README 中英的命令表把示例改成 `--selection "1,3-5"` 并注明支持区间，`docs/workflow.md` 补一句「与 `screen --add` 共用一个解析器，写错报「导入范围有误」而不是静默选成 0 篇」；`docs/zotero.md` 的导入规则新增两条——写入失败按 `connection` / `rejected` / `api` 分档上报（断连先回查一次，其实已提交时报「写入已完成，只是响应中断」并给出 key），以及读目录本身失败时导入直接暂停，不会被说成「Collection 路径不存在」。

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
