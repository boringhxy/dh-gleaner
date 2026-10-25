"""题名匹配工具。

用于把用户给出的题名列表匹配到 pending.json 中的文章编号。
题名匹配采用保守策略：唯一匹配才能进入导入；未匹配或多候选时只输出确认表。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List

from .models import STATUS_IMPORTED, STATUS_PRESENTED, STATUS_SELECTED, Article


@dataclass
class TitleCandidate:
    article: Article
    score: float


@dataclass
class TitleMatch:
    requested: str
    normalized: str
    status: str  # matched / ambiguous / unmatched
    candidates: List[TitleCandidate]


_SPLIT_RE = re.compile(r"[\n；;]+")
_LEADING_NUM_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.、.)）]|[（(]\d+[）)])\s*")
_DASHES = str.maketrans({
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
})
_QUOTES = str.maketrans({
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
})


def parseTitleList(text: str) -> List[str]:
    """解析用户输入的题名列表，支持换行、分号和简单编号。"""
    titles: List[str] = []
    for part in _SPLIT_RE.split(text or ""):
        item = _LEADING_NUM_RE.sub("", part).strip()
        item = item.strip(' "\'《》')
        if item:
            titles.append(item)
    return titles


def normalizeTitle(title: str) -> str:
    """归一化题名：统一全半角、引号、破折号，并去除空白和标点符号。"""
    text = unicodedata.normalize("NFKC", title or "")
    text = text.translate(_DASHES).translate(_QUOTES)
    chars = []
    for ch in text.lower():
        category = unicodedata.category(ch)
        if category[0] in {"P", "S", "Z"}:
            continue
        chars.append(ch)
    return "".join(chars)


def _titleScore(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        return 0.97
    return SequenceMatcher(None, query, candidate).ratio()


def matchTitlesToArticles(
    requestedTitles: List[str],
    articles: List[Article],
    threshold: float = 0.86,
    ambiguityDelta: float = 0.03,
) -> List[TitleMatch]:
    """把用户题名按顺序匹配到文章列表。

    只有唯一候选且分数达到阈值时标记为 matched；多个近似候选会标记 ambiguous。
    """
    articleNorms = [(article, normalizeTitle(article.title)) for article in articles]
    matches: List[TitleMatch] = []
    for requested in requestedTitles:
        norm = normalizeTitle(requested)
        scored = [
            TitleCandidate(article=article, score=_titleScore(norm, articleNorm))
            for article, articleNorm in articleNorms
        ]
        scored = [candidate for candidate in scored if candidate.score >= threshold]
        scored.sort(key=lambda item: item.score, reverse=True)
        if not scored:
            matches.append(TitleMatch(requested=requested, normalized=norm, status="unmatched", candidates=[]))
            continue

        top = scored[0].score
        candidates = [candidate for candidate in scored if top - candidate.score <= ambiguityDelta]
        exact = [candidate for candidate in candidates if candidate.score == 1.0]
        if len(exact) == 1:
            matches.append(TitleMatch(requested=requested, normalized=norm, status="matched", candidates=exact))
        elif len(candidates) == 1:
            matches.append(TitleMatch(requested=requested, normalized=norm, status="matched", candidates=candidates))
        else:
            matches.append(TitleMatch(requested=requested, normalized=norm, status="ambiguous", candidates=candidates[:5]))
    return matches


def allTitleMatchesConfirmed(matches: List[TitleMatch]) -> bool:
    """是否所有题名都唯一匹配，且没有重复指向同一篇文章。"""
    seen = set()
    for match in matches:
        if match.status != "matched" or len(match.candidates) != 1:
            return False
        idx = getattr(match.candidates[0].article, "_globalIndex", 0)
        if idx in seen:
            return False
        seen.add(idx)
    return True


def articlesFromTitleMatches(matches: List[TitleMatch], articles: List[Article]) -> List[Article]:
    """按用户题名顺序返回选中文章。"""
    selectedIds = {id(match.candidates[0].article) for match in matches if match.status == "matched" and match.candidates}
    for article in articles:
        if article.status != STATUS_IMPORTED and not article.zoteroKey:
            article.status = STATUS_SELECTED if id(article) in selectedIds else STATUS_PRESENTED
    return [match.candidates[0].article for match in matches if match.status == "matched" and match.candidates]


def selectionStringFromTitleMatches(matches: List[TitleMatch]) -> str:
    """生成可复用的编号选择字符串。"""
    indexes = []
    for match in matches:
        if match.status == "matched" and match.candidates:
            indexes.append(str(getattr(match.candidates[0].article, "_globalIndex", 0)))
    return ",".join(indexes)


def renderTitleMatchReport(matches: List[TitleMatch]) -> str:
    """渲染题名匹配确认表。"""
    lines = ["# 题名匹配确认表", ""]
    lines.append("| # | 用户题名 | 状态 | 匹配编号 | 匹配标题 | 分数 |")
    lines.append("|---|----------|------|----------|----------|------|")
    for i, match in enumerate(matches, 1):
        if not match.candidates:
            lines.append(f"| {i} | {_escapeCell(match.requested)} | 未匹配 | - | - | - |")
            continue
        if match.status == "matched":
            candidate = match.candidates[0]
            idx = getattr(candidate.article, "_globalIndex", 0)
            lines.append(
                f"| {i} | {_escapeCell(match.requested)} | 已唯一匹配 | {idx} | "
                f"{_escapeCell(candidate.article.title)} | {candidate.score:.2f} |"
            )
            continue
        descriptions = []
        scores = []
        indexes = []
        for candidate in match.candidates:
            idx = getattr(candidate.article, "_globalIndex", 0)
            indexes.append(str(idx))
            descriptions.append(f"#{idx} {candidate.article.title}")
            scores.append(f"{candidate.score:.2f}")
        lines.append(
            f"| {i} | {_escapeCell(match.requested)} | 多候选 | {_escapeCell(', '.join(indexes))} | "
            f"{_escapeCell(' / '.join(descriptions))} | {_escapeCell(', '.join(scores))} |"
        )

    matched = sum(1 for match in matches if match.status == "matched")
    ambiguous = sum(1 for match in matches if match.status == "ambiguous")
    unmatched = sum(1 for match in matches if match.status == "unmatched")
    lines.append("")
    lines.append("## 汇总")
    lines.append(f"- 用户题名: {len(matches)} 条")
    lines.append(f"- 已唯一匹配: {matched} 条")
    lines.append(f"- 多候选: {ambiguous} 条")
    lines.append(f"- 未匹配: {unmatched} 条")
    selection = selectionStringFromTitleMatches(matches)
    if selection:
        lines.append(f"- 唯一匹配编号: {selection}")
    return "\n".join(lines)


def _escapeCell(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )
