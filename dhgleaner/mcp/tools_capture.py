"""MCP 写本地工具：抓目录、导出筛选表、结清清单。

这些工具**不写 Zotero**，只写本数据目录（pending.json / review.md / state.json / xlsx）。
抓取类工具默认 `dryRun=True`：先看清会抓到什么、会不会覆盖旧清单，再决定是否落盘。
"""

from __future__ import annotations

from ..config import loadConfig
from ..http_util import FetchBlocked
from ..paths import getPaths
from ..review_spreadsheet import exportReviewSpreadsheet as writeReviewSpreadsheet
from ..selection import resolveSkipAll
from ..service import (
    captureHarvest,
    captureJournalChannel,
    loadPending,
    loadPendingData,
    savePending,
    stateManager,
)
from ..service import (
    captureIssue as _captureIssue,
)
from ..service import (
    recordManualIssueUrl as _recordManualIssueUrl,
)
from ..validation import (
    ValidationError,
    resolveCaptureRequest,
    resolveChannelRequest,
    resolveHarvestRequest,
    resolveManualSourceRequest,
)
from .errors import classifyFailure, failure, success
from .payloads import capturePayload, dataDirInfo

_DRY_RUN_NOTE = "dryRun=True：本次没有写盘。确认无误后用 dryRun=False 落盘。"


def _finishCapture(outcome, dryRun: bool, hint: str = "") -> dict:
    payload = capturePayload(outcome)
    if outcome.status == "failed":
        reason = outcome.reason or "未捕获到文章，旧筛选清单未被覆盖。"
        kind = classifyFailure(reason) if outcome.reason else "empty_parse"
        extras = {"suggestedAction": hint} if hint else {}
        return failure(reason, kind=kind, **extras, **payload)
    if outcome.status == "suspect":
        return failure(
            f"抓取疑似误抓，旧筛选清单未被覆盖：{outcome.reason}",
            kind="issue_mismatch",
            **payload,
        )
    return success(dryRun=dryRun, dryRunNote=_DRY_RUN_NOTE if dryRun else "", **payload)


def captureIssue(
    journal: str = "",
    year: int | None = None,
    issue: int | None = None,
    volume: int | None = None,
    url: str = "",
    selectAllJournals: bool = False,
    dedupe: bool = False,
    dryRun: bool = True,
    limit: int = 200,
) -> dict:
    """抓取某刊某期的目录与摘要（或按 url 抓指定目录页）。

    抓取阶段只读网页、只写本数据目录，**绝不写 Zotero、不下载 PDF**。

    Args:
        journal: 期刊名，支持别名（dhr / szrw / zgszrw / tadh / tsgzz / tsglt）。
        year: 目标年份。与 issue 同时给出才能定位期次。
        issue: 目标期号。
        volume: 目标卷号，仅《数字人文研究》等有卷号的刊需要。
        url: 手动指定目录页地址；适用于当期页失效、或站点需要特定单期 URL 的情况。
        selectAllJournals: 显式抓取配置中的全部期刊（与 journal 互斥）。
        dedupe: 按 state.json 过滤已处理文章。
        dryRun: 默认 True，只抓不落盘；设为 False 才会覆盖 pending.json / review.md。
        limit: 返回的文章行数上限。
    """
    cfg = loadConfig()
    try:
        target, journalName = resolveCaptureRequest(
            cfg,
            journal=journal,
            allJournals=selectAllJournals,
            year=year,
            issue=issue,
            volume=volume,
            url=url,
        )
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")

    try:
        outcome = _captureIssue(
            cfg, target=target, journalName=journalName, url=url, dedupe=dedupe, dryRun=dryRun
        )
    except FetchBlocked as e:
        return failure(str(e), error=e, kind="blocked")
    except Exception as e:
        return failure(f"抓取过程出错：{e}", error=e)
    return _finishCapture(
        outcome,
        dryRun,
        hint="可用 url 参数直接指定该期的目录页地址。",
    )


def captureChannel(
    journal: str,
    channel: str,
    url: str = "",
    dedupe: bool = False,
    dryRun: bool = True,
    limit: int = 200,
) -> dict:
    """按栏目抓取跨期文章清单（如《图书馆杂志》的「数字人文」栏目）。

    Args:
        journal: 期刊名，支持别名。
        channel: 栏目名。
        url: 手动指定栏目页地址；未指定时用配置里的栏目源。
        dedupe: 按 state.json 过滤已处理文章。
        dryRun: 默认 True，只抓不落盘。
        limit: 返回的文章行数上限。
    """
    cfg = loadConfig()
    try:
        journalConfig, journalName, channelName = resolveChannelRequest(cfg, journal=journal, channel=channel)
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")

    try:
        outcome = captureJournalChannel(
            cfg,
            journalConfig=journalConfig,
            journalName=journalName,
            channelName=channelName,
            url=url,
            dedupe=dedupe,
            dryRun=dryRun,
        )
    except FetchBlocked as e:
        return failure(str(e), error=e, kind="blocked")
    except Exception as e:
        return failure(f"抓取过程出错：{e}", error=e)
    return _finishCapture(
        outcome,
        dryRun,
        hint=f"可用 url 参数直接指定《{journalName}》「{channelName}」栏目的目录页地址。",
    )


def harvestYear(
    year: int | None = None,
    journal: str = "",
    withAbstracts: bool = True,
    dhOnly: bool = True,
    dedupe: bool = False,
    dryRun: bool = True,
    limit: int = 200,
) -> dict:
    """按年枚举散篇期刊的全年目录，并按 DH 关键词筛选（不写 Zotero、不下 PDF）。

    针对没有稳定「当期目录页」、只能逐年翻过刊库的散篇期刊（现代情报、情报科学、
    中国图书馆学报、国家图书馆学刊、数字图书馆论坛、图书情报知识、信息资源管理学报等）。
    结果同样落到 pending/review，因此 screen / import 下游照常可用。

    Args:
        year: 目标年份（必填），如 2026。
        journal: 期刊名，支持别名；留空则 harvest 配置中所有 harvestOnly 散篇期刊。
        withAbstracts: 是否抓摘要（默认 True）。关闭更快，但 DH 关键词只按标题命中。
        dhOnly: True（默认）只保留命中 DH 关键词表的文章；False 保留全年全目录并打标签。
        dedupe: 按 state.json 过滤已处理文章。
        dryRun: 默认 True，只抓不落盘；设为 False 才会覆盖 pending.json / review.md。
        limit: 返回的文章行数上限。
    """
    cfg = loadConfig()
    try:
        journalName, yearInt = resolveHarvestRequest(cfg, journal=journal, year=year)
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")

    try:
        outcome = captureHarvest(
            cfg,
            year=yearInt,
            journalName=journalName,
            withAbstracts=withAbstracts,
            dedupe=dedupe,
            dhOnly=dhOnly,
            dryRun=dryRun,
        )
    except FetchBlocked as e:
        return failure(str(e), error=e, kind="blocked")
    except Exception as e:
        return failure(f"harvest 过程出错：{e}", error=e)
    return _finishCapture(
        outcome,
        dryRun,
        hint="该刊可能不支持按年 harvest，或过刊库地址已变更；可用 capture_issue 抓当期。",
    )


def exportReviewSpreadsheet(output: str = "") -> dict:
    """把当前待筛清单导出成 Excel 勾选表（写本数据目录）。

    Args:
        output: 输出路径；留空则写到数据目录下的 review_selection.xlsx。
    """
    pending = loadPendingData()
    markdown, articles = loadPending()
    if not pending or not articles:
        return failure("当前没有待筛文章，请先抓取目录。", kind="no_pending")

    path = getPaths().spreadsheet if not output else getPaths().dataDir / output
    writeReviewSpreadsheet(path, articles, pending)
    return success(
        path=str(path),
        articleCount=len(articles),
        columns="「筛选」页的「是否导入」列填「是」；导入时用 spreadsheet 参数指向本文件。",
    )


def markPendingSkipped(confirm: bool = False) -> dict:
    """把当前待导入文章全部标记为「都不要」并写入 state.json。

    这是有副作用的操作：被标记的文章以后不会再出现在清单里，因此默认拒绝执行。

    Args:
        confirm: 必须显式为 True 才会执行。
    """
    if confirm is not True:
        return failure(
            "本操作会把当前待导入文章全部标记为已处理，之后不会再出现在清单里。"
            "确认要这么做时请传 confirm=true。",
            kind="invalid_input",
            refused=True,
            requiresConfirmation=True,
        )

    cfg = loadConfig()
    markdown, articles = loadPending()
    if not articles:
        return failure("当前没有待导入文章。", kind="no_pending")

    outcome = resolveSkipAll(articles, stateManager(cfg))
    savePending(markdown, articles)
    return success(
        **dataDirInfo(),
        skippedCount=outcome.skippedCount,
        message=outcome.message,
        note="只改本地 state.json 与 pending.json，未触碰 Zotero。",
    )


def recordIssueUrl(journal: str, url: str, source: str = "") -> dict:
    """记下人工发现的最新一期链接（如微信公众号目录推文），只写本地 state.json。

    《数字人文》这类集刊的最早公告在公众号里，而公众号在微信外没有可列举的文章列表：
    新推文只能由人贴进来。记下来之后 `discover_latest` 才会把这一期认作最新已知期次，
    并在官方逐篇页滞后时提醒「还差几期」。

    Args:
        journal: 期刊名，支持别名。
        url: 该期目录页 / 目录推文地址。
        source: 人工型发现源的 id（如 wechat_toc）；该刊只有一个个人工源时可省略。
    """
    cfg = loadConfig()
    try:
        journalName, sourceId = resolveManualSourceRequest(cfg, journal, url, source)
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")
    info = _recordManualIssueUrl(cfg, journalName, sourceId, url)
    return success(
        **dataDirInfo(),
        **info,
        note="只写 state.json，不抓网页、不覆盖待筛清单、不碰 Zotero。",
        nextStep=f"接着调 discover_latest(journal='{journalName}') 确认该链接宣告的是哪一期。",
    )


def register(server) -> None:
    """把写本地工具挂到 MCP server 上。"""
    server.add_tool(captureIssue, name="capture_issue",
                    description="抓取某刊某期目录与摘要（默认 dryRun，只抓不落盘；不写 Zotero）")
    server.add_tool(captureChannel, name="capture_channel",
                    description="按栏目抓取跨期文章清单（默认 dryRun；不写 Zotero）")
    server.add_tool(harvestYear, name="harvest_year",
                    description="按年枚举散篇期刊全年目录并按 DH 关键词筛选（默认 dryRun；不写 Zotero）")
    server.add_tool(exportReviewSpreadsheet, name="export_review_spreadsheet",
                    description="把待筛清单导出为 Excel 勾选表（写本数据目录）")
    server.add_tool(markPendingSkipped, name="mark_pending_skipped",
                    description="把当前待导入文章全部标记为已处理（需 confirm=true）")
    server.add_tool(recordIssueUrl, name="record_issue_url",
                    description="记下人工发现的最新一期链接（微信目录推文等），只写 state.json")


__all__ = [
    "captureChannel",
    "captureIssue",
    "exportReviewSpreadsheet",
    "harvestYear",
    "markPendingSkipped",
    "recordIssueUrl",
    "register",
]
