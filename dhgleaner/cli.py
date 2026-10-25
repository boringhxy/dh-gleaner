#!/usr/bin/env python3
"""数字人文期刊采集器 — CLI 入口。

三阶段工作流：
  1. capture  — 按用户指定年期捕获期刊文章
  2. export-review / review — 导出或查看待筛文章清单
  3. import   — 导入用户确认的文章到 Zotero

用法:
  dhgleaner capture --journal 图书馆论坛 --year 2026 --issue 3
  dhgleaner export-review                     # 导出 Excel 筛选表
  dhgleaner import --selection "1,3,5"        # 只导入选中编号
  dhgleaner abstract --index 2                # 查看某篇摘要

本模块只负责「解析参数 → 调 service → 打印给人看」。
业务逻辑在 service / selection / validation，MCP 工具复用同一套。
文章数据通过 <数据目录>/data/pending.json 在阶段间传递。
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import List, NoReturn

from . import __version__
from .config import credentialHint, isZoteroConfigured, loadConfig
from .discovery import renderDiscoveries
from .logging_setup import forceUtf8, setupLogging
from .paths import configTemplatePath, getPaths, setDataDir
from .presenter import getArticleByIndex, renderAbstract
from .review_spreadsheet import exportReviewSpreadsheet
from .selection import (
    STATUS_EMPTY,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIRM,
    STATUS_OK,
    STATUS_SKIP_ALL,
    STATUS_TITLE_CONFIRM_REQUIRED,
    SelectionOutcome,
    readTitles,
    resolveAll,
    resolveBySelection,
    resolveBySpreadsheet,
    resolveByTitlesFromList,
    resolveSkipAll,
)
from .selection_basket import (
    addIndexes,
    loadBasket,
    parseIndexSpec,
    removeIndexes,
    renderArticleRows,
    renderBasketSummary,
    saveBasket,
    searchArticles,
    selectedArticles,
)
from .service import (
    captureHarvest,
    captureIssue,
    captureJournalChannel,
    collectDoctorChecks,
    discoverLatest,
    ensureCollections,
    loadPending,
    loadPendingData,
    planCollections,
    previewArticles,
    recordManualIssueUrl,
    runImport,
    saveCredentials,
    savePending,
    stateManager,
    writeTextArtifact,
)
from .validation import (
    ValidationError,
    resolveCaptureRequest,
    resolveChannelRequest,
    resolveDiscoverRequest,
    resolveHarvestRequest,
    resolveManualSourceRequest,
)
from .zotero_client import ZoteroClient


def _fail(message: str) -> NoReturn:
    """CLI 层的输入错误出口：沿用原来的退出码语义（stderr + exit 1）。"""
    raise SystemExit(message)


#: 抓取类命令的退出码。用 3 而不是 2 —— 2 已经被 argparse 的参数错误占用，
#: 脚本里两者混在一起就没法区分「我命令写错了」和「站点没给数据」。
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_SUSPECT = 3


def _captureExitCode(outcome) -> int:
    """把抓取质量映射成退出码，供 cron / CI 判断是否需要人工看一眼。

    `suspect` 也返回非零：清单是抓到了，但闸门认为它不像有效目录，旧的
    `pending.json` 没有被覆盖 —— 自动化的调用方需要知道这次不算数。
    """
    if outcome.status == "success":
        return EXIT_OK
    if outcome.status == "suspect":
        return EXIT_SUSPECT
    return EXIT_FAILED


def _ok(label: str, ok: bool, detail: str = ""):
    icon = "✅" if ok else "⚠️"
    suffix = f" — {detail}" if detail else ""
    print(f"{icon} {label}{suffix}")


def _printCaptureAdvisories(outcome) -> None:
    """把每本刊的失败原因与时效提醒打到终端。

    过去失败只进日志文件，用户看到的只是「文章数偏少」，无法区分
    「站点拒绝自动化」和「网络抖动，重试就好」——两者的应对完全相反。
    时效提醒同理：抓到旧期与「确实没有新刊」在清单上长得一模一样。
    """
    if outcome.failures:
        blocked = [f for f in outcome.failures if f.kind == "blocked"]
        retryable = [f for f in outcome.failures if f.kind != "blocked"]
        if blocked:
            print("\n⛔ 以下期刊拒绝自动化访问，重试无用（请用 --url 指定可直接打开的目录页，或转人工）：")
            for failure in blocked:
                print(f"  - {failure.describe()}")
        if retryable:
            print("\n⚠️ 以下期刊本次没抓到，可稍后重试：")
            for failure in retryable:
                print(f"  - {failure.describe()}")
    for warning in getattr(outcome, "warnings", None) or []:
        print(f"\n⏳ {warning}")


def _isInteractive() -> bool:
    """能否安全地向用户提问；非交互环境（MCP、CI、管道）一律返回 False。"""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _printDoctorSummary(cfg: dict):
    print("\n# 环境自检")
    for check in collectDoctorChecks(cfg).checks:
        _ok(check.label, check.ok, check.detail)


def saveTextArtifact(path: Path, content: str, label: str) -> bool:
    """保存运行报告（携带终端提示的 CLI 版包装）。"""
    error = writeTextArtifact(path, content)
    if error:
        print(f"{label}不可写，未保存: {path} ({error})", file=sys.stderr)
        return False
    print(f"{label}已保存到 {path}")
    return True


# --------------------------------------------------------------------------
# 阶段一：捕获
# --------------------------------------------------------------------------

def cmdDoctor(args, cfg):
    """检查 agent 的真实运行条件。"""
    print("# 数字人文期刊采集器 自检\n")
    report = collectDoctorChecks(cfg, checkZotero=args.zotero, checkNetwork=args.network)
    for check in report.checks:
        _ok(check.label, check.ok, check.detail)


def _printCollectionPlan(report) -> None:
    """把只读预检结果打成一张表，让用户先看清楚「会往哪写」。"""
    print("| 期刊 | Collection 路径 | 缺失层级 | 状态 |")
    print("|------|-----------------|----------|------|")
    for row in report.rows:
        fullPath = " / ".join(row.path) if row.path else "—"
        missing = " / ".join(row.missing) if row.missing else "—"
        if row.error:
            status = f"⚠️ 预检出错: {row.error}"
        elif row.complete:
            status = "✅ 已就绪"
        else:
            status = "待创建"
        print(f"| 《{row.journal}》 | {fullPath} | {missing} | {status} |")


def cmdInitCollections(args, cfg):
    """补齐 Zotero 里缺失的期刊 Collection 目录。

    默认只读预览（列出会建哪些目录）；加 `--yes` 才真正创建。
    这条命令是「显式建目录」的入口，导入流程本身仍不会擅自建目录。
    """
    journals = [args.journal] if getattr(args, "journal", None) else None
    report = planCollections(cfg)
    if not report.connected:
        print(f"⚠️ {report.connectionError}。")
        print(credentialHint())
        return

    print("# Zotero Collection 目录预检\n")
    _printCollectionPlan(report)

    missing = [row for row in report.rows if row.missing]
    if journals:
        missing = [row for row in missing if row.journal in journals]
    errored = [row for row in report.rows if row.error and (not journals or row.journal in journals)]
    if errored:
        # 预检失败的行 missing 是空的，若继续往下判「无缺失」就会误报「都已就绪」，
        # 400 Invalid user ID 这类凭据错误正是这样被掩盖掉的。此时不能建目录。
        print(f"\n⚠️ {len(errored)} 本期刊的目录预检失败——「查不到缺口」不等于「已就绪」，本次未写入任何目录。")
        print("失败原因见上表「预检出错」列。")
        print(credentialHint())
        return
    if not missing:
        print("\n✅ 目标期刊的 Collection 目录都已就绪，无需创建。")
        return

    if not getattr(args, "yes", False):
        print("\n以上「待创建」目录尚未写入 Zotero（本命令默认只预览）。")
        print("确认无误后运行：dhgleaner init-collections --yes")
        if journals:
            print(f"（当前只针对：{'、'.join(journals)}）")
        return

    created, recheck = ensureCollections(cfg, journals=journals)
    if created:
        print(f"\n✅ 已新建 {len(created)} 个 Collection 目录：{' / '.join(created)}")
    else:
        print("\n⚠️ 未新建任何目录（可能已被并发创建，或创建失败，详见日志）。")
    stillMissing = [row for row in recheck.rows if row.missing and (not journals or row.journal in journals)]
    if stillMissing:
        print("仍有缺口：")
        for row in stillMissing:
            print(f"  - 《{row.journal}》 缺: {' / '.join(row.missing)}")


def cmdInit(args, cfg):
    """首次使用引导：录入凭据 → 测试连接 → 可选补齐目录 → 自检。

    非交互环境下不阻塞提问，只打印手动配置步骤并跑一次自检。
    """
    paths = getPaths()
    print("# 数字人文期刊采集器 — 初始化引导\n")
    print(f"数据目录: {paths.dataDir}（来源: {paths.describeSource()}）")
    print(f"凭据只写入: {paths.configLocalPath}（不会提交、不会上传、不回显）\n")

    if not _isInteractive():
        print("检测到非交互环境，跳过输入式引导。请手动完成配置：")
        print("  1) 设置环境变量 ZOTERO_LIBRARY_ID 与 ZOTERO_API_KEY（优先级最高，不落盘）；或")
        print(f"  2) 把模板 {configTemplatePath()} 复制为 {paths.configLocalPath}，填入你自己的 Zotero 凭据。")
        print("  然后运行 `dhgleaner doctor --zotero` 验证连接。")
        _printDoctorSummary(cfg)
        return

    configured, missingFields = isZoteroConfigured(cfg)
    if configured:
        print("✅ 已检测到 Zotero 凭据，跳过录入。如需更换，请手动编辑 config.local.json。")
    else:
        print(f"尚未配置凭据（缺 {missingFields}）。现在录入你自己的 Zotero Web API 凭据。")
        print("获取路径：登录 zotero.org → Settings → Security → Applications → 新建 API key。")
        try:
            libraryId = input("Zotero 用户/库 ID（个人库为纯数字）: ").strip()
            apiKey = getpass.getpass("Zotero API key（输入不回显）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未写入任何凭据。稍后可重新运行 `dhgleaner init`。")
            return
        if not libraryId or not apiKey:
            print("⚠️ 两项都必填，已放弃写入。")
            return
        ok, detail = saveCredentials(libraryId, apiKey)
        if not ok:
            print(f"⚠️ 写入 config.local.json 失败: {detail}")
            return
        print(f"✅ 凭据已写入 {detail}（权限已收紧为仅本人可读写）。")
        cfg = loadConfig()

    print("\n测试 Zotero 连接...")
    if not ZoteroClient(cfg.get("zotero", {})).testConnection():
        print("⚠️ 连接失败。请核对凭据与网络后重跑 `dhgleaner doctor --zotero`。")
        return
    print("✅ Zotero 连接正常。")

    report = planCollections(cfg)
    missing = report.missingRows
    if missing:
        print("\n以下期刊的 Collection 目录尚不完整：")
        for row in missing:
            print(f"  - 《{row.journal}》 缺: {' / '.join(row.missing)}")
        try:
            answer = input("\n现在就创建这些目录吗？(y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer in ("y", "yes"):
            created, _ = ensureCollections(cfg)
            print(f"✅ 已新建 {len(created)} 个目录：{' / '.join(created)}" if created else "未新建任何目录。")
        else:
            print("已跳过。稍后可运行 `dhgleaner init-collections --yes` 创建。")
    else:
        print("\n✅ 所有期刊 Collection 目录已就绪。")

    _printDoctorSummary(cfg)
    print("\n下一步示例：dhgleaner capture --journal 图书馆论坛 --year 2026 --issue 3")


def cmdCapture(args, cfg):
    """阶段一：捕获文章。"""
    try:
        target, journalName = resolveCaptureRequest(
            cfg,
            journal=args.journal,
            allJournals=bool(args.all_journals),
            year=args.year,
            issue=args.issue,
            volume=args.volume,
            url=args.url or "",
        )
    except ValidationError as e:
        _fail(str(e))

    outcome = captureIssue(
        cfg,
        target=target,
        journalName=journalName,
        url=args.url or "",
        dedupe=bool(args.dedupe),
    )
    print(outcome.markdown)
    _printCaptureAdvisories(outcome)

    paths = getPaths()
    if outcome.status == "success":
        print(f"\n--- 共捕获 {outcome.articleCount} 篇文章，筛选清单已保存到 {paths.review}，待导入数据已保存到 {paths.pending} ---")
        if outcome.backups:
            print(f"已自动备份旧筛选数据: {'；'.join(str(path) for path in outcome.backups)}")
        print('本阶段不会导入 Zotero，也不会下载 PDF。请先阅读筛选清单，再用 `dhgleaner import --selection "编号"` 只导入需要的文章。')
    elif outcome.status == "suspect":
        print(f"\n--- ⚠️ 本次抓取疑似误抓，未覆盖原有筛选清单: {paths.review} ---")
        print(f"原因: {outcome.reason}")
        print(f"本次 suspect 状态已写入 {paths.captureStatus}；当前 review.md 仍是上一次成功捕获的旧内容。")
    else:
        print(f"\n--- ⚠️ 本次未捕获到文章，已保留原有筛选清单: {paths.review} ---")
        print(f"⚠️ 当前 review.md 仍是上一次成功捕获的旧内容；本次失败状态已写入 {paths.captureStatus}")
        print("如目标期次网页可直接访问，请重试：dhgleaner capture --journal 期刊名 --url 目录页URL")

    return _captureExitCode(outcome)


def cmdCaptureChannel(args, cfg):
    """捕获栏目型文章清单。"""
    try:
        journalConfig, journalName, channelName = resolveChannelRequest(
            cfg, journal=args.journal, channel=args.channel
        )
    except ValidationError as e:
        _fail(str(e))

    outcome = captureJournalChannel(
        cfg,
        journalConfig=journalConfig,
        journalName=journalName,
        channelName=channelName,
        url=args.url or "",
        dedupe=bool(args.dedupe),
    )
    print(outcome.markdown)
    _printCaptureAdvisories(outcome)

    paths = getPaths()
    if outcome.status == "success":
        print(f"\n--- 栏目《{channelName}》共捕获 {outcome.articleCount} 篇文章，筛选清单已保存到 {paths.review} ---")
        if outcome.backups:
            print(f"已自动备份旧筛选数据: {'；'.join(str(path) for path in outcome.backups)}")
        print("本阶段不会导入 Zotero，也不会下载 PDF。请筛选编号后再运行 import --selection。")
    elif outcome.status == "suspect":
        print(f"\n--- ⚠️ 栏目抓取疑似误抓，未覆盖原有筛选清单: {paths.review} ---")
        print(f"原因: {outcome.reason}")
        print(f"本次 suspect 状态已写入 {paths.captureStatus}；当前 review.md 仍是上一次成功捕获的旧内容。")
    else:
        print(f"\n--- ⚠️ 栏目《{channelName}》未捕获到文章，已保留原有筛选清单: {paths.review} ---")
        print(f"本次失败状态已写入 {paths.captureStatus}")

    return _captureExitCode(outcome)


def cmdHarvest(args, cfg):
    """按年 harvest 散篇期刊：全年全目录 → DH 关键词筛 → 落盘待筛清单。

    与 capture 并列的第三种采集流程，同样只写 pending/review，不碰 Zotero、不下 PDF。
    """
    try:
        journalName, year = resolveHarvestRequest(cfg, journal=args.journal, year=args.year)
    except ValidationError as e:
        _fail(str(e))

    outcome = captureHarvest(
        cfg,
        year=year,
        journalName=journalName,
        withAbstracts=not args.no_abstracts,
        dedupe=bool(args.dedupe),
        dhOnly=not args.all_catalog,
        dryRun=bool(args.dry_run),
    )
    print(outcome.markdown)
    _printCaptureAdvisories(outcome)

    paths = getPaths()
    scope = f"《{journalName}》" if journalName else "全部散篇期刊"
    if outcome.status == "success":
        kept = "全目录" if args.all_catalog else "DH 命中文章"
        print(f"\n--- {year} 年 {scope} harvest 完成：保留{kept} {outcome.articleCount} 篇，筛选清单已保存到 {paths.review} ---")
        if outcome.backups:
            print(f"已自动备份旧筛选数据: {'；'.join(str(path) for path in outcome.backups)}")
        print("本阶段不会导入 Zotero，也不会下载 PDF。请筛选编号后再运行 import --selection。")
    elif outcome.status == "suspect":
        print(f"\n--- ⚠️ harvest 疑似误抓，未覆盖原有筛选清单: {paths.review} ---")
        print(f"原因: {outcome.reason}")
        print(f"本次 suspect 状态已写入 {paths.captureStatus}；当前 review.md 仍是上一次成功捕获的旧内容。")
    else:
        print(f"\n--- ⚠️ {year} 年 {scope} 未 harvest 到文章，已保留原有筛选清单: {paths.review} ---")
        if outcome.reason:
            print(f"原因: {outcome.reason}")
        print(f"本次失败状态已写入 {paths.captureStatus}")
        if args.dry_run:
            print("（本次为 --dry-run 预览，未落盘；去掉 --dry-run 可写入待筛清单。）")

    return _captureExitCode(outcome)


# --------------------------------------------------------------------------
# 阶段〇：发现层 —— 各刊「最新已知期次」
# --------------------------------------------------------------------------

def cmdDiscover(args, cfg):
    """探测各刊当前最新的已知期次，并说明该用哪条命令拿到它。"""
    if args.record_url:
        try:
            journalName, sourceId = resolveManualSourceRequest(
                cfg, args.journal, args.record_url, args.source
            )
        except ValidationError as e:
            _fail(str(e))
        recordManualIssueUrl(cfg, journalName, sourceId, args.record_url)
        print(f"已记录《{journalName}》人工来源 {sourceId}: {args.record_url}")
        print(f"接着运行 dhgleaner discover --journal {journalName} 确认它宣告的是哪一期。")
        return EXIT_OK

    try:
        journalName = resolveDiscoverRequest(cfg, args.journal)
    except ValidationError as e:
        _fail(str(e))

    discoveries = discoverLatest(cfg, journalName=journalName, record=not args.no_record)
    if args.json:
        print(json.dumps([item.toDict() for item in discoveries], ensure_ascii=False, indent=2))
    else:
        scope = f"《{journalName}》" if journalName else "全部期刊"
        print(f"发现层探测：{scope}（探测结果只写 state.json，不覆盖待筛清单、不碰 Zotero）")
        print(renderDiscoveries(discoveries))
        if args.no_record:
            print("\n（--no-record：本次未把结论写入 state.json）")

    # 全部源都标了 manual（只能等人）不算失败：那是在等人，不是抓坏了。
    missing = [
        item.journal
        for item in discoveries
        if not item.frontier and {s.status for s in item.sources} - {"manual"}
    ]
    if missing:
        print(f"\n以下期刊没能探出最新期次：{'、'.join(missing)}")
    return EXIT_FAILED if missing else EXIT_OK


# --------------------------------------------------------------------------
# 阶段二：查看与筛选
# --------------------------------------------------------------------------

def cmdReview(args, cfg):
    """重新显示最近一次捕获的筛选清单。"""
    markdown, articles = loadPending()
    if not articles:
        print("没有待筛选的文章。请先运行 `dhgleaner capture --journal 期刊名 --year 年份 --issue 期号`。")
        return
    print(markdown)


def cmdExportReview(args, cfg):
    """导出 Excel 筛选表。"""
    pending = loadPendingData()
    if not pending:
        print("没有待筛选的文章。请先运行 capture 或 capture-channel。")
        return
    _, articles = loadPending()
    if not articles:
        print("没有待筛选的文章。请先运行 capture 或 capture-channel。")
        return
    if args.format != "xlsx":
        _fail("当前仅支持 --format xlsx")
    output = Path(args.output).expanduser() if args.output else getPaths().spreadsheet
    if not output.is_absolute():
        output = getPaths().dataDir / output
    exportReviewSpreadsheet(output, articles, pending)
    print(f"Excel 筛选表已保存到 {output}")
    print("打开表格后，在“筛选”页的“是否导入”列选择“是”；筛完后运行：")
    print(f'dhgleaner import --spreadsheet "{output}"')


def cmdScreen(args, cfg):
    """筛选篮：渐进式筛选待导入文章。"""
    markdown, articles = loadPending()
    if not articles:
        print("没有待筛选的文章。请先运行 capture 或 capture-channel。")
        return

    maxIndex = max((getattr(article, "_globalIndex", 0) for article in articles), default=0)
    basket = loadBasket(getPaths().selection, articles)
    changed = False

    if args.clear:
        basket.indexes = []
        changed = True
        print("已清空筛选篮。")

    if args.add:
        indexes = parseIndexSpec(args.add, maxIndex=maxIndex)
        addIndexes(basket, indexes)
        changed = True
        print(f"已加入筛选篮: {','.join(str(i) for i in indexes)}")

    if args.remove:
        indexes = parseIndexSpec(args.remove, maxIndex=maxIndex)
        removeIndexes(basket, indexes)
        changed = True
        print(f"已从筛选篮移除: {','.join(str(i) for i in indexes)}")

    if changed:
        saveBasket(getPaths().selection, basket)
        print(f"筛选篮已保存到 {getPaths().selection}")

    if args.search:
        matched = searchArticles(articles, args.search)
        print(f"# 搜索结果：{args.search}")
        print("")
        if matched:
            print(renderArticleRows(matched, basket.indexes))
        else:
            print("未匹配到文章。")
        print("")
        print('可继续运行：dhgleaner screen --add "编号"')
        return

    if args.list:
        print("# 待筛文章清单")
        print("")
        print(renderArticleRows(articles, basket.indexes))
        print("")
        print('可继续运行：dhgleaner screen --add "1,3-5" 或 --search "关键词"')
        return

    if args.import_selected:
        selected = selectedArticles(articles, basket)
        if not selected:
            print("筛选篮为空，未导入 Zotero。请先用 `screen --add` 加入文章。")
            return
        print(f"将导入筛选篮中的 {len(selected)} 篇文章到 Zotero...")
        print("")
        print(_runImport(selected, articles, markdown, cfg))
        return

    print(renderBasketSummary(articles, basket))


def cmdAbstract(args, cfg):
    """查看某篇文章的摘要。"""
    _, articles = loadPending()
    if not articles:
        print("没有待查看的文章。请先运行 `dhgleaner capture`。")
        return
    article = getArticleByIndex(articles, args.index)
    if not article:
        print(f"未找到编号 {args.index} 的文章。")
        return
    print(renderAbstract(article))


# --------------------------------------------------------------------------
# 阶段三：导入
# --------------------------------------------------------------------------

def _runImport(selected: List, articles: List, markdown: str, cfg: dict) -> str:
    """唯一会写 Zotero 的调用点；由 cmdImport / cmdScreen 在人工选择之后触发。"""
    outcome = runImport(selected, articles, markdown, cfg)
    return outcome.report


def _resolveImportOutcome(args, articles: List, pending: dict) -> SelectionOutcome:
    """把四条互斥的导入路径（表格 / 题名 / 编号 / 全部）规约成一个结果。"""
    spreadsheet = getattr(args, "spreadsheet", None)
    if spreadsheet:
        mixed = any([
            bool(getattr(args, "selection", None)),
            bool(getattr(args, "titles", None)),
            bool(getattr(args, "titles_file", None)),
            bool(getattr(args, "all", False)),
        ])
        if mixed:
            raise ValidationError("--spreadsheet 不能和 --selection、--titles、--titles-file 或 --all 同时使用")
        return resolveBySpreadsheet(spreadsheet, articles, pending)

    titleInputs = readTitles(getattr(args, "titles", None), getattr(args, "titles_file", None))
    if titleInputs:
        return resolveByTitlesFromList(
            titleInputs, articles, confirm=bool(getattr(args, "confirm_titles", False))
        )

    if getattr(args, "all", False):
        return resolveAll(articles)
    selection = getattr(args, "selection", None)
    if selection is not None:
        if not selection.strip():
            # `--selection "$PICK"` 里变量没展开时会传进来空串，而空串在口令表里
            # 等同于「都不要」——一次手滑就把整张待筛清单标成已处理并封口期次。
            raise ValidationError("--selection 不能为空；请输入编号，或明确输入「都不要」")
        return resolveBySelection(selection, articles)
    return SelectionOutcome(
        status=STATUS_EMPTY,
        message='请指定导入范围: --selection "1,3,5"、--titles/--titles-file，或 --all',
    )


def cmdImport(args, cfg):
    """阶段三：导入选中文章。"""
    pending = loadPendingData()
    markdown, articles = loadPending()
    if not articles:
        print("没有待导入的文章。请先运行 `dhgleaner capture`。")
        return

    try:
        outcome = _resolveImportOutcome(args, articles, pending)
    except ValidationError as e:
        print(f"输入有误：{e}")
        return

    if outcome.matchReport:
        print(outcome.matchReport)
        saveTextArtifact(getPaths().titleMatchReport, outcome.matchReport, "题名匹配报告")

    if outcome.status == STATUS_NEEDS_CONFIRM:
        print(f"\n{outcome.message}请修正题名，或改用 --selection 指定确认后的编号。")
        return
    if outcome.status == STATUS_TITLE_CONFIRM_REQUIRED:
        print(f"\n{outcome.message}")
        print(f'如确认无误，可运行：dhgleaner import --selection "{outcome.selectionHint}"')
        print("或在当前题名命令后追加 --confirm-titles，按你给出的题名顺序导入。")
        return
    if getattr(args, "dry_run", False) and outcome.status in (STATUS_OK, STATUS_SKIP_ALL):
        # --dry-run 必须盖住每一条导入路径且不留副作用。旧实现把预览挂在
        # `--spreadsheet` 分支上，`import --all --dry-run` 会带着「我只看看」
        # 的意图真的写进 Zotero、改完 state.json 再覆写 pending.json。
        print("预览模式，未写入 Zotero，也未改动待筛清单和 state.json。")
        if outcome.status == STATUS_OK:
            print("")
            print("# 导入预览")
            for row in previewArticles(outcome.selected):
                print(f"{row['position']}. [{row['index']}] {row['title']}")
        else:
            print(f"去掉 --dry-run 后将执行：{outcome.message}")
        print("\n确认无误后去掉 --dry-run 重新运行。")
        return
    if outcome.status == STATUS_SKIP_ALL:
        marked = resolveSkipAll(articles, stateManager(cfg))
        savePending(markdown, articles)
        print(f"{marked.message}，未导入 Zotero。")
        return
    if outcome.status in (STATUS_EMPTY, STATUS_INVALID):
        print(outcome.message)
        return
    if outcome.status != STATUS_OK:
        print(f"未处理的选择状态: {outcome.status}")
        return

    print(f"{outcome.message}到 Zotero...")
    print("")
    print(_runImport(outcome.selected, articles, markdown, cfg))


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

def main():
    # 帮助文本与所有结果输出都是中文：Windows 非 UTF-8 区域的控制台默认 cp1252，
    # 不先固定编码的话连 `--help` 都会抛 UnicodeEncodeError。
    forceUtf8(sys.stdout)
    parser = argparse.ArgumentParser(
        description="数字人文期刊采集器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dataDirHelp = "覆盖数据目录（单次生效）；未指定时依次取 DHGLEANER_DATA_DIR、当前目录、~/.dhgleaner"
    parser.add_argument("--version", action="version", version=f"dh-gleaner {__version__}", help="打印版本号后退出")
    parser.add_argument("--data-dir", help=dataDirHelp)
    sub = parser.add_subparsers(dest="command", help="子命令")

    pCap = sub.add_parser("capture", help="按指定年期或目录 URL 捕获期刊文章")
    pCap.add_argument("--journal", help="指定期刊名；短别名支持 dhr/szrw/zgszrw/tadh/tsgzz/tsglt")
    pCap.add_argument("--all-journals", action="store_true", help="显式抓取配置中的全部期刊")
    pCap.add_argument("--year", type=int, help="目标年份，如 2025")
    pCap.add_argument("--issue", type=int, help="目标期号，如 4")
    pCap.add_argument("--volume", type=int, help="目标卷号（主要用于《数字人文研究》，可选）")
    pCap.add_argument("--url", help="手动指定目录页 URL；使用时必须同时指定 --journal")
    pCap.add_argument("--dedupe", action="store_true", help="目标期次抓取时也按 state.json 过滤已处理文章")

    pChan = sub.add_parser("capture-channel", help="按栏目抓取跨期文章清单")
    pChan.add_argument("--journal", required=True, help="指定期刊名；如 图书馆杂志")
    pChan.add_argument("--channel", required=True, help="栏目名；如 数字人文")
    pChan.add_argument("--url", help="手动指定栏目页 URL；未指定时使用 config.json 中的 channelSources")
    pChan.add_argument("--dedupe", action="store_true", help="按 state.json 过滤已处理文章")

    pHar = sub.add_parser("harvest", help="按年枚举散篇期刊全目录并按 DH 关键词筛选")
    pHar.add_argument("--journal", help="指定期刊名；留空则 harvest 配置中所有 harvestOnly 散篇期刊")
    pHar.add_argument("--year", type=int, required=True, help="目标年份，如 2026")
    pHar.add_argument("--no-abstracts", action="store_true", help="不抓摘要（更快，但 DH 关键词只按标题命中）")
    pHar.add_argument("--all-catalog", action="store_true", help="保留全年全目录并打 DH 标签，而非只留 DH 命中文章")
    pHar.add_argument("--dedupe", action="store_true", help="按 state.json 过滤已处理文章")
    pHar.add_argument("--dry-run", action="store_true", help="只打印结果，不覆盖 pending/review")

    pDisc = sub.add_parser(
        "discover",
        help="探测各刊当前最新的已知期次，并给出拿到它该跑的命令",
    )
    pDisc.add_argument("--journal", help="只探测指定期刊；留空则探测配置中的全部期刊")
    pDisc.add_argument("--json", action="store_true", help="输出结构化 JSON，供脚本或 Agent 消费")
    pDisc.add_argument("--no-record", action="store_true", help="只报告结论，不写入 state.json 的 latestKnown")
    pDisc.add_argument(
        "--record-url",
        help="记下人工发现的最新一期链接（如微信公众号目录推文），供 tier-1 发现源使用",
    )
    pDisc.add_argument("--source", help="配合 --record-url：指定人工型发现源的 id")

    pRev = sub.add_parser("review", help="查看最近一次捕获的目录和摘要筛选清单")

    pExport = sub.add_parser("export-review", help="导出 Excel 筛选表，方便在表格软件中勾选文章")
    pExport.add_argument("--format", choices=["xlsx"], default="xlsx", help="导出格式，目前支持 xlsx")
    pExport.add_argument("--output", help="输出文件路径；默认 data/review_selection.xlsx")

    pScreen = sub.add_parser("screen", help="筛选篮：搜索、逐步加入/移除并导入文章")
    pScreen.add_argument("--list", action="store_true", help="显示紧凑待筛文章清单")
    pScreen.add_argument("--search", type=str, help="按题名、作者、栏目、摘要等关键词搜索")
    pScreen.add_argument("--add", type=str, help="加入筛选篮，支持 1,3-5")
    pScreen.add_argument("--remove", type=str, help="从筛选篮移除，支持 1,3-5")
    pScreen.add_argument("--clear", action="store_true", help="清空筛选篮")
    pScreen.add_argument("--import", dest="import_selected", action="store_true", help="导入筛选篮中的文章")

    pImp = sub.add_parser("import", help="导入选中文章到 Zotero")
    pImp.add_argument("--selection", type=str, help='文章编号，支持逐个与区间，如 "1,3,5"、"1-7"')
    pImp.add_argument("--titles", type=str, help="按题名匹配待导入文章；用分号或换行分隔")
    pImp.add_argument("--titles-file", type=str, help="从文本文件读取题名列表；每行一条，也支持分号分隔")
    pImp.add_argument("--confirm-titles", action="store_true", help="题名全部唯一匹配后，按用户题名顺序导入")
    pImp.add_argument("--spreadsheet", type=str, help="读取 Excel 筛选表中“是否导入=是”的文章")
    pImp.add_argument("--dry-run", action="store_true", help="预览将导入的文章，不写入 Zotero、不改动待筛清单（适用于所有导入路径）")
    pImp.add_argument("--all", action="store_true", help="导入全部")

    pDoc = sub.add_parser("doctor", help="自检依赖、目录、Zotero 和网络")
    pDoc.add_argument("--zotero", action="store_true", help="实际连接 Zotero 并检查 Collection")
    pDoc.add_argument("--network", action="store_true", help="实际抓取两份期刊网页并解析")

    pAbs = sub.add_parser("abstract", help="查看某篇文章摘要")
    pAbs.add_argument("--index", type=int, required=True, help="文章编号")

    pInit = sub.add_parser("init", help="首次使用引导：录入 Zotero 凭据、测试连接、可选补齐目录")

    pInitColl = sub.add_parser(
        "init-collections", help="补齐 Zotero 里缺失的期刊 Collection 目录（默认只预览，加 --yes 才创建）"
    )
    pInitColl.add_argument("--journal", help="只处理指定期刊；默认处理配置中的全部期刊")
    pInitColl.add_argument("--yes", action="store_true", help="确认创建缺失目录（不加则只读预览）")

    # 子命令之后也允许写 --data-dir，两种位置等价；
    # default=SUPPRESS 是关键：否则子解析器会用默认值覆盖顶层已解析的值。
    for subParser in (pCap, pChan, pHar, pDisc, pRev, pExport, pScreen, pImp, pDoc, pAbs, pInit, pInitColl):
        subParser.add_argument("--data-dir", default=argparse.SUPPRESS, help=dataDirHelp)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    setDataDir(getattr(args, "data_dir", None))
    cfg = loadConfig()
    setupLogging(cfg.get("logFile", "logs/capture.log"))

    handlers = {
        "capture": cmdCapture,
        "capture-channel": cmdCaptureChannel,
        "harvest": cmdHarvest,
        "discover": cmdDiscover,
        "review": cmdReview,
        "export-review": cmdExportReview,
        "screen": cmdScreen,
        "import": cmdImport,
        "doctor": cmdDoctor,
        "abstract": cmdAbstract,
        "init": cmdInit,
        "init-collections": cmdInitCollections,
    }
    exitCode = handlers[args.command](args, cfg)
    if exitCode:
        # 用 SystemExit 而不是 return：`dhgleaner`、`python -m dhgleaner`、
        # `python main.py` 三个入口都是直接调 main()，return 值会被丢掉。
        raise SystemExit(exitCode)


if __name__ == "__main__":
    main()
