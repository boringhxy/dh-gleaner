"""把内部数据结构翻译成 MCP 工具可返回的形状。

这些函数保证「同一份数据在 CLI 与 MCP 里含义一致」，同时把绝对路径、
内部字段名收敛成稳定的对外契约。
"""

from __future__ import annotations

from typing import Sequence

from ..models import Article
from ..paths import getPaths
from ..service import CaptureOutcome


def articleRow(article: Article, *, includeUrls: bool = True) -> dict:
    row = {
        "index": getattr(article, "_globalIndex", 0),
        "title": article.title,
        "journal": article.journal,
        "issue": article.issueDisplay or article.issueInfo().label(),
        "section": article.section or "未分类",
        "authors": list(article.authors),
        "pages": article.pagesStr(),
        "hasAbstract": bool(article.abstract),
        "abstractLength": len(article.abstract or ""),
        "hasPdf": bool(article.pdfUrl),
        "status": article.status,
    }
    if includeUrls:
        row["articleUrl"] = article.articleUrl
        row["pdfUrl"] = article.pdfUrl
    return row


def articleRows(articles: Sequence[Article], limit: int | None = None, *, includeUrls: bool = True) -> list[dict]:
    items = list(articles)
    if limit is not None:
        items = items[:limit]
    return [articleRow(article, includeUrls=includeUrls) for article in items]


def capturePayload(outcome: CaptureOutcome, *, articleLimit: int = 200) -> dict:
    """抓取结果的对外摘要；不含整篇 markdown（体积大，且有 review 文件可读）。"""
    return {
        "journal": outcome.journal,
        "issue": outcome.issue,
        "status": outcome.status,
        "quality": outcome.quality,
        "articleCount": outcome.articleCount,
        "reason": outcome.reason,
        "wrotePending": outcome.wrotePending,
        "reviewPath": str(getPaths().review),
        "pendingPath": str(getPaths().pending),
        "backups": [str(path) for path in outcome.backups],
        "failures": [f.toDict() for f in outcome.failures],
        "blockedJournals": outcome.blockedJournals,
        "freshnessWarnings": list(outcome.warnings or []),
        "articles": articleRows(outcome.articles, articleLimit),
        "articlesTruncated": outcome.articleCount > articleLimit,
    }


def dataDirInfo() -> dict:
    paths = getPaths()
    return {
        "dataDir": str(paths.dataDir),
        "dataDirSource": paths.describeSource(),
        "configLocalPath": str(paths.configLocalPath),
    }
