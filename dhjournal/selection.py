"""阶段三：把「用户的选择」解析成待导入文章列表。

`cmdImport` 原先一个函数里塞了四条互斥路径（表格 / 题名 / 编号 / 全部），
而且边解析边 print。这里把四条路径拆成四个纯函数，统一返回 `SelectionOutcome`，
打印留给 CLI，MCP 工具则直接读结构体。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

from .models import STATUS_PRESENTED, STATUS_SELECTED, Article
from .paths import getPaths
from .presenter import applySelection
from .review_spreadsheet import SpreadsheetValidationError, loadSpreadsheetSelection
from .state import StateManager
from .title_matcher import (
    allTitleMatchesConfirmed,
    articlesFromTitleMatches,
    matchTitlesToArticles,
    parseTitleList,
    renderTitleMatchReport,
    selectionStringFromTitleMatches,
)
from .validation import SKIP_TOKENS, ValidationError

log = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_NEEDS_CONFIRM = "needs_confirm"
STATUS_TITLE_CONFIRM_REQUIRED = "title_confirm_required"
STATUS_SKIP_ALL = "skipped_all"
STATUS_NO_PENDING = "no_pending"


@dataclass
class SelectionOutcome:
    """解析结果：既能给 CLI 打印，也能直接给 MCP 当返回值。"""

    status: str
    selected: List[Article] = field(default_factory=list)
    message: str = ""
    matchReport: str = ""
    selectionHint: str = ""
    skippedCount: int = 0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def readTitles(titles: str | None = None, titlesFile: str | None = None) -> list[str]:
    """把 --titles 与 --titles-file 合并成题名列表。"""
    chunks: list[str] = []
    if titles:
        chunks.append(titles)
    if titlesFile:
        path = Path(titlesFile).expanduser()
        if not path.is_absolute():
            path = getPaths().dataDir / path
        if not path.exists():
            raise ValidationError(f"题名文件不存在: {path}")
        chunks.append(path.read_text(encoding="utf-8"))
    return parseTitleList("\n".join(chunks))


def resolveAll(articles: Sequence[Article]) -> SelectionOutcome:
    for article in articles:
        article.status = STATUS_SELECTED
    selected = list(articles)
    return SelectionOutcome(status=STATUS_OK, selected=selected, message=_byIndexMessage(len(selected)))


def _byIndexMessage(count: int) -> str:
    return f"将按筛选清单编号顺序导入 {count} 篇文章"


def resolveBySelection(selection: str | None, articles: Sequence[Article]) -> SelectionOutcome:
    """按筛选清单编号解析，如 "1,3,5"。"""
    normalized = (selection or "").strip()
    if normalized in SKIP_TOKENS:
        return SelectionOutcome(status=STATUS_SKIP_ALL, message="全部标记为不要")
    selected = applySelection(list(articles), normalized)
    if not selected:
        return SelectionOutcome(status=STATUS_EMPTY, message="未选中任何文章。")
    return SelectionOutcome(status=STATUS_OK, selected=selected, message=_byIndexMessage(len(selected)))


def resolveByTitlesFromList(
    titleInputs: Sequence[str],
    articles: Sequence[Article],
    confirm: bool = False,
) -> SelectionOutcome:
    """按题名匹配。未全部唯一匹配时只出匹配报告，不导入。"""
    if not titleInputs:
        return SelectionOutcome(status=STATUS_EMPTY, message="未提供任何题名")

    matches = matchTitlesToArticles(list(titleInputs), list(articles))
    report = renderTitleMatchReport(matches)
    if not allTitleMatchesConfirmed(matches):
        return SelectionOutcome(
            status=STATUS_NEEDS_CONFIRM,
            message="题名列表存在未匹配或多候选项，未导入 Zotero。",
            matchReport=report,
        )

    hint = selectionStringFromTitleMatches(matches)
    if not confirm:
        return SelectionOutcome(
            status=STATUS_TITLE_CONFIRM_REQUIRED,
            message="题名已全部唯一匹配，但本次只是确认匹配，尚未导入 Zotero。",
            matchReport=report,
            selectionHint=hint,
        )
    selected = articlesFromTitleMatches(matches, list(articles))
    return SelectionOutcome(
        status=STATUS_OK,
        selected=selected,
        message=f"将按用户题名顺序导入 {len(selected)} 篇文章",
        matchReport=report,
        selectionHint=hint,
    )


def resolveByTitles(titles: str | None, titlesFile: str | None, articles: Sequence[Article]) -> SelectionOutcome:
    """从 --titles / --titles-file 读取题名后匹配。"""
    return resolveByTitlesFromList(readTitles(titles, titlesFile), articles)


def resolveBySpreadsheet(
    spreadsheetPath: str | Path,
    articles: Sequence[Article],
    pendingMeta: dict,
) -> SelectionOutcome:
    """读取 Excel 筛选表中「是否导入=是」的文章。"""
    path = Path(spreadsheetPath).expanduser()
    if not path.is_absolute():
        path = getPaths().dataDir / path
    if not path.exists():
        return SelectionOutcome(status=STATUS_INVALID, message=f"筛选表不存在: {path}")
    try:
        selected = loadSpreadsheetSelection(path, list(articles), pendingMeta)
    except SpreadsheetValidationError as e:
        return SelectionOutcome(status=STATUS_INVALID, message=f"筛选表校验失败：{e}")
    if not selected:
        return SelectionOutcome(status=STATUS_EMPTY, message="筛选表中没有标记为“是”的文章，未导入 Zotero。")
    for article in selected:
        article.status = STATUS_SELECTED
    return SelectionOutcome(
        status=STATUS_OK,
        selected=selected,
        message=f"将导入筛选表中标记为“是”的 {len(selected)} 篇文章",
    )


def markAllPresentedAsSkipped(articles: Sequence[Article], state: StateManager) -> int:
    """把当前待导入文章全部标记为 skipped，并结清已全部处理完的期次。"""
    with state.batch():
        for article in articles:
            state.markArticleProcessed(
                article.journal,
                article.articleKey(),
                zoteroKey="",
                title=article.title,
                status="skipped",
            )
            article.status = STATUS_PRESENTED

        seen = set()
        for article in articles:
            issue = article.issueInfo()
            issueKey = (article.journal, issue.key())
            if issueKey in seen:
                continue
            seen.add(issueKey)
            issueArticles = [a for a in articles if a.journal == article.journal and a.issueInfo().key() == issue.key()]
            if issueArticles and all(state.isArticleProcessed(a.journal, a.articleKey()) for a in issueArticles):
                state.markIssueProcessed(article.journal, issue)
    return len(articles)


def resolveSkipAll(articles: Sequence[Article], state: StateManager) -> SelectionOutcome:
    count = markAllPresentedAsSkipped(articles, state)
    return SelectionOutcome(
        status=STATUS_SKIP_ALL,
        message=f"已将当前待导入的 {count} 篇文章全部标记为都不要",
        skippedCount=count,
    )
