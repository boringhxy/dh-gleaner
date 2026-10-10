"""MCP 导入工具：唯一会写 Zotero 的地方，带双重闸门。

设计红线（写在代码里，不只是文档里）：

1. 解析阶段**只读**——`planImport` 用 `collectionPlan()` 检查目录，
   绝不调用会自动建目录的 `locateJournalCollection()`。
2. 写入阶段要**同时**满足 `confirm=true` 且 `dryRun=false`。
   任一条件不满足就返回 `refused`，一个字都不往 Zotero 写。
3. 默认参数是「拒绝」而不是「允许」：`confirm=False, dryRun=True`。
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
    SelectionOutcome,
    readTitles,
    resolveAll,
    resolveBySelection,
    resolveBySpreadsheet,
    resolveByTitlesFromList,
)
from ..selection_basket import loadBasket, selectedArticles
from ..service import loadPending, loadPendingData, previewArticles, runImport
from ..validation import ValidationError
from ..zotero_client import ZoteroClient
from .errors import failure, success
from .payloads import dataDirInfo

_STATUS_LABEL = {
    STATUS_OK: "resolved",
    STATUS_EMPTY: "empty",
    STATUS_INVALID: "invalid",
    STATUS_NEEDS_CONFIRM: "needs_confirm",
    STATUS_TITLE_CONFIRM_REQUIRED: "title_confirm_required",
    STATUS_SKIP_ALL: "skipped_all",
}


def _resolve(cfg, articles, pending, *, selection, titles, titlesFile, spreadsheet,
             selectAll, useBasket, confirmTitles):
    """把参数解析成 SelectionOutcome。全部为只读操作。"""
    if useBasket:
        basket = loadBasket(getPaths().selection, articles)
        chosen = selectedArticles(articles, basket)
        return SelectionOutcome(
            status=STATUS_OK if chosen else STATUS_EMPTY,
            selected=chosen,
            message=f"筛选篮中有 {len(chosen)} 篇文章",
        )
    if spreadsheet:
        return resolveBySpreadsheet(spreadsheet, articles, pending)
    titleInputs = readTitles(titles, titlesFile)
    if titleInputs:
        return resolveByTitlesFromList(titleInputs, articles, confirm=confirmTitles)
    if selectAll:
        return resolveAll(articles)
    if selection:
        return resolveBySelection(selection, articles)
    raise ValidationError(
        "请指定导入范围：selection / titles / titlesFile / spreadsheet / selectAll / useBasket"
    )


def _collectionPlan(cfg, journalNames) -> dict:
    """只读预检每个目标期刊的 Collection 路径（绝不新建目录）。"""
    zotero = ZoteroClient(cfg.get("zotero", {}))
    plans = {}
    for name in sorted(set(journalNames)):
        plans[name] = zotero.collectionPlan(name)
    return {
        "autoCreateCollection": bool(cfg.get("zotero", {}).get("autoCreateCollection", False)),
        "journals": plans,
    }


def importToZotero(
    selection: str = "",
    titles: str = "",
    titlesFile: str = "",
    spreadsheet: str = "",
    selectAll: bool = False,
    useBasket: bool = False,
    confirmTitles: bool = False,
    confirm: bool = False,
    dryRun: bool = True,
    limit: int = 200,
) -> dict:
    """把选中的文章写入 Zotero。**默认拒绝执行**，需要显式确认。

    写入条件（两者必须同时满足）：`confirm=true` 且 `dryRun=false`。
    只给其中一个都会返回 `refused=true` 的说明，不会写任何条目。

    建议流程：先 `preview_import` 看清清单 → 用户确认 → 再调用本工具。

    Args:
        selection: 文章编号，如 "1,3,5"。
        titles: 题名列表，分号或换行分隔。
        titlesFile: 题名文件路径（相对路径基于数据目录）。
        spreadsheet: Excel 筛选表路径，读取「是否导入=是」的行。
        selectAll: 导入全部待筛文章。
        useBasket: 使用筛选篮中的文章。
        confirmTitles: 题名全部唯一匹配时视为已确认。
        confirm: 必须显式为 True。
        dryRun: 默认为 True；只有显式设为 False 才真正写库。
        limit: 返回的文章行数上限。
    """
    pending = loadPendingData()
    markdown, articles = loadPending()
    if not articles:
        return failure("当前没有待导入文章，请先抓取目录。", kind="no_pending")

    cfg = loadConfig()
    try:
        outcome = _resolve(
            cfg, articles, pending,
            selection=selection, titles=titles, titlesFile=titlesFile,
            spreadsheet=spreadsheet, selectAll=selectAll, useBasket=useBasket,
            confirmTitles=confirmTitles,
        )
    except ValidationError as e:
        return failure(str(e), kind="invalid_input")

    statusLabel = _STATUS_LABEL.get(outcome.status, outcome.status)
    plan = previewArticles(outcome.selected) if outcome.selected else []
    collectionPlan = _collectionPlan(cfg, [row["journal"] for row in plan]) if plan else {}

    common = {
        "status": statusLabel,
        "selectionHint": outcome.selectionHint,
        "matchReport": outcome.matchReport,
        "count": len(plan),
        "articles": plan[:limit],
        "collectionPlan": collectionPlan,
        **dataDirInfo(),
    }

    if outcome.status == STATUS_SKIP_ALL:
        return success(
            message=outcome.message,
            **common,
            note="选择是「都不要」。如需结清这批文章，请调用 mark_pending_skipped。",
        )
    if outcome.status != STATUS_OK or not plan:
        return failure(
            outcome.message or "没有解析出可导入的文章。",
            kind="invalid_input",
            suggestedAction="请先用 preview_import 确认编号或题名，再重试。",
            **common,
        )

    if confirm is not True or dryRun is not False:
        missing = []
        if confirm is not True:
            missing.append("confirm=true")
        if dryRun is not False:
            missing.append("dryRun=false")
        return success(
            message=outcome.message,
            **common,
            refused=True,
            requiresConfirmation=True,
            confirmReceived=bool(confirm),
            dryRun=dryRun,
            note=(
                "尚未写入 Zotero。写库需要同时满足：" + " 与 ".join(missing) +
                "。请先让用户确认上面这份清单，再带上两个参数重试。"
            ),
        )

    result = runImport(outcome.selected, articles, markdown, cfg)
    if result.aborted:
        kind = "not_configured" if "连接失败" in result.abortReason else "issue_mismatch"
        return failure(
            result.abortReason or "预检未通过，未写入任何条目。",
            kind=kind,
            imported=0,
            skipped=result.skipped,
            failed=result.failed,
            wroteNothing=True,
            reportPath=str(result.reportPath) if result.reportPath else "",
            report=result.report,
            **common,
        )
    return success(
        message=outcome.message,
        **common,
        imported=result.imported,
        skipped=result.skipped,
        failed=result.failed,
        reportPath=str(result.reportPath) if result.reportPath else "",
        createdCollections=result.createdCollections,
        report=result.report,
    )


def register(server) -> None:
    """把导入工具挂到 MCP server 上。"""
    server.add_tool(
        importToZotero,
        name="import_to_zotero",
        description="把选中文章写入 Zotero（唯一会写库的工具；默认拒绝，需 confirm=true 且 dryRun=false）",
    )


__all__ = ["importToZotero", "register"]
