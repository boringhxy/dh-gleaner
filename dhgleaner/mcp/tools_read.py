"""MCP 只读工具：看一眼，不改任何东西。

这些工具绝不写磁盘、不写 Zotero、不发请求（除 run_doctor 显式要求时）。
`run_doctor` 的 Zotero/网络检查需要用户在参数里主动开启。
"""

from __future__ import annotations

from ..config import loadConfig
from ..paths import getPaths
from ..selection import (
    STATUS_EMPTY,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIRM,
    STATUS_OK,
    STATUS_SKIP_ALL,
    STATUS_TITLE_CONFIRM_REQUIRED,
    readTitles,
    resolveAll,
    resolveBySelection,
    resolveBySpreadsheet,
    resolveByTitlesFromList,
)
from ..selection_basket import loadBasket, searchArticles, selectedArticles
from ..service import collectDoctorChecks, loadCaptureStatus, loadPending, loadPendingData, previewArticles
from ..validation import ValidationError
from .errors import failure, success
from .payloads import articleRow, articleRows, dataDirInfo


def listJournals() -> dict:
    """列出本工具支持的期刊、抓取方式与其固有局限。"""
    cfg = loadConfig()
    journals = []
    for journal in cfg.get("journals", []):
        channelSources = journal.get("channelSources") or []
        journals.append({
            "name": journal.get("name", ""),
            "parser": journal.get("parser", ""),
            "hasCurrentIssueUrl": bool(journal.get("currentIssueUrl")),
            "currentIssueUrl": journal.get("currentIssueUrl", ""),
            "harvestOnly": bool(journal.get("harvestOnly")),
            "channels": [source.get("channel", "") for source in channelSources],
            "autoDownloadPdf": bool(journal.get("autoDownloadPdf", False)),
            "pdfNote": journal.get("pdfNote", ""),
            "publishRule": journal.get("publishRule", ""),
        })
    return success(
        **dataDirInfo(),
        count=len(journals),
        journals=journals,
        note="抓取公开目录页，不绕过验证码或登录；『先筛选、后导入』是硬约束。harvestOnly=true 的散篇期刊用 harvest_year 按年采集。",
    )


def getCaptureStatus() -> dict:
    """最近一次抓取的状态：成功/疑似误抓/失败，以及当前清单是否过期。"""
    status = loadCaptureStatus()
    if not status:
        return success(
            **dataDirInfo(),
            hasStatus=False,
            message="还没有抓取记录。可先用 capture_issue 抓一期目录。",
        )
    _, articles = loadPending()
    return success(
        **dataDirInfo(),
        hasStatus=True,
        capturedAt=status.get("capturedAt", ""),
        status=status.get("status", ""),
        message=status.get("message", ""),
        reviewIsStale=bool(status.get("reviewIsStale", False)),
        results=status.get("results", []),
        pendingArticleCount=len(articles),
    )


def listPendingArticles(
    journal: str = "",
    issue: str = "",
    limit: int = 200,
    offset: int = 0,
    includeUrls: bool = False,
) -> dict:
    """列出当前待筛文章（可选按期刊、期次过滤）。

    Args:
        journal: 只看该刊；留空表示全部。
        issue: 只看期次标签（如 "2026年 第6卷 第2期"）中含该子串的文章。
        limit: 最多返回多少条。
        offset: 跳过前多少条，便于翻页。
        includeUrls: 是否带上原文与 PDF 链接。
    """
    _, articles = loadPending()
    if not articles:
        return failure("当前没有待筛文章。", kind="no_pending")

    filtered = articles
    if journal:
        filtered = [a for a in filtered if a.journal == journal]
    if issue:
        filtered = [a for a in filtered if issue in (a.issueDisplay or a.issueInfo().label())]

    window = filtered[offset: offset + max(limit, 0)]
    return success(
        total=len(filtered),
        returned=len(window),
        offset=offset,
        articles=articleRows(window, includeUrls=includeUrls),
        reviewIsStale=bool(loadCaptureStatus().get("reviewIsStale", False)),
    )


def getArticleAbstract(index: int) -> dict:
    """读取某篇文章的完整信息与摘要。

    Args:
        index: 筛选清单里的编号（从 1 开始）。
    """
    _, articles = loadPending()
    if not articles:
        return failure("当前没有待筛文章。", kind="no_pending")
    for article in articles:
        if getattr(article, "_globalIndex", 0) == index:
            return success(
                **articleRow(article),
                abstract=article.abstract,
                note="" if article.abstract else "该刊详情页可能需验证码，摘要需手动补充。",
            )
    return failure(f"未找到编号 {index} 的文章。", kind="invalid_input", maxIndex=len(articles))


def searchPendingArticles(query: str, limit: int = 50) -> dict:
    """按关键词（题名/作者/栏目/摘要）搜索当前待筛文章。

    Args:
        query: 关键词。
        limit: 最多返回多少条。
    """
    _, articles = loadPending()
    if not articles:
        return failure("当前没有待筛文章。", kind="no_pending")
    matched = searchArticles(articles, query)
    return success(
        query=query,
        total=len(matched),
        returned=len(matched[:limit]),
        articles=articleRows(matched, limit),
    )


def previewImport(
    selection: str = "",
    titles: str = "",
    titlesFile: str = "",
    spreadsheet: str = "",
    selectAll: bool = False,
    useBasket: bool = False,
    confirmTitles: bool = False,
    limit: int = 200,
) -> dict:
    """**只读**预览：按给定条件解析出将要导入的文章，绝不写入任何地方。

    返回的 `status` 说明解析结果：
    resolved（可以导入）/ empty（没选中）/ needs_confirm（题名未唯一匹配）/
    title_confirm_required（题名匹配成功但还需显式确认）/ skipped_all（选择了全部不要）/
    invalid（表格校验失败）。

    Args:
        selection: 文章编号，如 "1,3,5"；也接受 "全部"。
        titles: 题名列表，分号或换行分隔。
        titlesFile: 题名文件路径（相对路径基于数据目录）。
        spreadsheet: Excel 筛选表路径，读取「是否导入=是」的行。
        selectAll: 导入全部。
        useBasket: 使用 screen 命令维护的筛选篮。
        confirmTitles: 题名全部唯一匹配时，是否按题名顺序视为已确认。
        limit: 最多返回多少条预览。
    """
    pending = loadPendingData()
    markdown, articles = loadPending()
    if not articles:
        return failure("当前没有待导入文章，请先抓取目录。", kind="no_pending")

    try:
        if useBasket:
            basket = loadBasket(getPaths().selection, articles)
            chosen = selectedArticles(articles, basket)
            rows = previewArticles(chosen)
            return success(
                status="resolved" if rows else "empty",
                mode="basket",
                count=len(rows),
                articles=rows[:limit],
                message=f"筛选篮中有 {len(rows)} 篇文章",
            )
        if spreadsheet:
            outcome = resolveBySpreadsheet(spreadsheet, articles, pending)
        else:
            titleInputs = readTitles(titles, titlesFile)
            if titleInputs:
                outcome = resolveByTitlesFromList(titleInputs, articles, confirm=confirmTitles)
            elif selectAll:
                outcome = resolveAll(articles)
            elif selection:
                outcome = resolveBySelection(selection, articles)
            else:
                return failure(
                    '请指定预览范围：selection / titles / titlesFile / spreadsheet / selectAll / useBasket',
                    kind="invalid_input",
                )
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")

    statusMap = {
        STATUS_OK: "resolved",
        STATUS_EMPTY: "empty",
        STATUS_INVALID: "invalid",
        STATUS_NEEDS_CONFIRM: "needs_confirm",
        STATUS_TITLE_CONFIRM_REQUIRED: "title_confirm_required",
        STATUS_SKIP_ALL: "skipped_all",
    }
    return success(
        status=statusMap.get(outcome.status, outcome.status),
        count=len(outcome.selected),
        message=outcome.message,
        selectionHint=outcome.selectionHint,
        matchReport=outcome.matchReport,
        articles=previewArticles(outcome.selected)[:limit],
    )


def getImportReport(maxChars: int = 8000) -> dict:
    """读取上一次写入 Zotero 的导入报告。

    Args:
        maxChars: 报告正文最多返回多少字符（过长会被截断）。
    """
    path = getPaths().importReport
    if not path.exists():
        return failure("还没有导入报告，说明本数据目录下尚未执行过导入。", kind="no_pending")
    text = path.read_text(encoding="utf-8")
    return success(
        path=str(path),
        length=len(text),
        truncated=len(text) > maxChars,
        report=text[:maxChars],
    )


def runDoctor(checkZotero: bool = False, checkNetwork: bool = False) -> dict:
    """自检：数据目录、配置模板、依赖、可写性，以及可选的 Zotero 与网络连通性。

    Args:
        checkZotero: 实际连接 Zotero 并逐刊检查 Collection（只读，不会新建目录）。
        checkNetwork: 实际抓取各刊当期目录页做解析验证（会发网络请求）。
    """
    cfg = loadConfig()
    report = collectDoctorChecks(cfg, checkZotero=checkZotero, checkNetwork=checkNetwork)
    return success(
        **dataDirInfo(),
        templatePath=report.templatePath,
        allPassed=report.ok,
        checks=[{"label": c.label, "ok": c.ok, "detail": c.detail} for c in report.checks],
    )


def register(server) -> None:
    """把只读工具挂到 MCP server 上。"""
    server.add_tool(listJournals, name="list_journals",
                    description="列出支持的期刊、抓取方式与固有局限（只读）")
    server.add_tool(getCaptureStatus, name="get_capture_status",
                    description="查看最近一次抓取的状态与清单是否过期（只读）")
    server.add_tool(listPendingArticles, name="list_pending_articles",
                    description="列出当前待筛文章，可按刊/期过滤、分页（只读）")
    server.add_tool(getArticleAbstract, name="get_article_abstract",
                    description="读取某篇待筛文章的完整信息与摘要（只读）")
    server.add_tool(searchPendingArticles, name="search_pending_articles",
                    description="按关键词搜索当前待筛文章（只读）")
    server.add_tool(previewImport, name="preview_import",
                    description="预览将要导入 Zotero 的文章，不写入任何地方（只读）")
    server.add_tool(getImportReport, name="get_import_report",
                    description="读取上一次导入 Zotero 的报告（只读）")
    server.add_tool(runDoctor, name="run_doctor",
                    description="自检运行环境；可选检查 Zotero 连接与网络抓取（只读）")
