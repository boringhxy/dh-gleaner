"""筛选篮工具。

把筛选阶段从“一次性输入编号”改成可逐步添加、移除、搜索和导入的轻量状态。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Article
from .title_matcher import normalizeTitle

_TZ = timezone(timedelta(hours=8))


@dataclass
class BasketState:
    indexes: List[int]
    stale: bool = False
    fingerprint: str = ""


def pendingFingerprint(articles: List[Article]) -> str:
    raw = "\n".join(
        f"{getattr(article, '_globalIndex', 0)}|{article.articleKey()}|{article.title}"
        for article in articles
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parseIndexSpec(spec: str, maxIndex: Optional[int] = None) -> List[int]:
    """解析编号表达式，支持 1,3-5、中文逗号、顿号和分号。"""
    normalized = (spec or "").replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",")
    indexes: List[int] = []
    seen = set()
    for part in normalized.split(","):
        token = part.strip()
        if not token:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if end < start:
                start, end = end, start
            candidates = range(start, end + 1)
        else:
            if not token.isdigit():
                raise ValueError(f"无法解析编号: {token}")
            candidates = [int(token)]
        for idx in candidates:
            if idx <= 0:
                continue
            if maxIndex is not None and idx > maxIndex:
                raise ValueError(f"编号超出当前清单范围: {idx}")
            if idx not in seen:
                indexes.append(idx)
                seen.add(idx)
    return indexes


def loadBasket(path: Path, articles: List[Article]) -> BasketState:
    fingerprint = pendingFingerprint(articles)
    if not path.exists():
        return BasketState(indexes=[], stale=False, fingerprint=fingerprint)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return BasketState(indexes=[], stale=True, fingerprint=fingerprint)
    if not isinstance(data, dict):
        return BasketState(indexes=[], stale=True, fingerprint=fingerprint)
    stale = data.get("pendingFingerprint") != fingerprint
    rawIndexes = data.get("selectedIndexes", []) if not stale else []
    valid = {getattr(article, "_globalIndex", 0) for article in articles}
    indexes: List[int] = []
    if isinstance(rawIndexes, list):
        for raw in rawIndexes:
            try:
                idx = int(raw)
            except (TypeError, ValueError):
                continue
            if idx in valid and idx not in indexes:
                indexes.append(idx)
    return BasketState(indexes=indexes, stale=stale, fingerprint=fingerprint)


def saveBasket(path: Path, state: BasketState) -> None:
    payload = {
        "updatedAt": datetime.now(_TZ).isoformat(timespec="seconds"),
        "pendingFingerprint": state.fingerprint,
        "selectedIndexes": state.indexes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def addIndexes(state: BasketState, indexes: Iterable[int]) -> BasketState:
    seen = set(state.indexes)
    for idx in indexes:
        if idx not in seen:
            state.indexes.append(idx)
            seen.add(idx)
    return state


def removeIndexes(state: BasketState, indexes: Iterable[int]) -> BasketState:
    remove = set(indexes)
    state.indexes = [idx for idx in state.indexes if idx not in remove]
    return state


def selectedArticles(articles: List[Article], state: BasketState) -> List[Article]:
    byIndex = {getattr(article, "_globalIndex", 0): article for article in articles}
    return [byIndex[idx] for idx in state.indexes if idx in byIndex]


def searchArticles(articles: List[Article], query: str) -> List[Article]:
    terms = [normalizeTitle(part) for part in re.split(r"\s+", query or "") if part.strip()]
    if not terms:
        return list(articles)
    matched = []
    for article in articles:
        haystack = normalizeTitle(" ".join([
            article.title or "",
            " ".join(article.authors or []),
            article.section or "",
            article.journal or "",
            article.abstract or "",
            article.issueDisplay or "",
        ]))
        if all(term in haystack for term in terms):
            matched.append(article)
    return matched


def renderArticleRows(articles: List[Article], selectedIndexes: Iterable[int]) -> str:
    selected = set(selectedIndexes)
    lines = ["| 选 | # | 期刊/期次 | 标题 | 作者 | 摘要 | PDF |", "|----|---|-----------|------|------|------|-----|"]
    for article in articles:
        idx = getattr(article, "_globalIndex", 0)
        mark = "x" if idx in selected else ""
        authors = ", ".join(article.authors[:2])
        if len(article.authors) > 2:
            authors += " 等"
        issue = article.issueDisplay or article.issueInfo().label()
        absFlag = f"有({len(article.abstract)}字)" if article.abstract else "无"
        pdf = article.pdfSize or ("有链接" if article.pdfUrl else "无")
        lines.append(
            f"| {mark} | {idx} | {_escapeCell(article.journal + ' ' + issue)} | "
            f"{_escapeCell(article.title)} | {_escapeCell(authors or '-')} | {_escapeCell(absFlag)} | {_escapeCell(pdf)} |"
        )
    return "\n".join(lines)


def renderBasketSummary(articles: List[Article], state: BasketState) -> str:
    selected = selectedArticles(articles, state)
    lines = ["# 筛选篮", ""]
    if state.stale:
        lines.append("> 当前 pending.json 已变化，旧筛选篮已自动置空。")
        lines.append("")
    lines.append(f"已选 {len(selected)} / {len(articles)} 篇")
    if selected:
        lines.append("")
        lines.append(renderArticleRows(selected, state.indexes))
        lines.append("")
        lines.append("导入命令: dhgleaner screen --import")
        lines.append(f"等价编号: dhgleaner import --selection \"{','.join(str(i) for i in state.indexes)}\"")
    else:
        lines.append("")
        lines.append("可用命令示例：")
        lines.append("- dhgleaner screen --list")
        lines.append("- dhgleaner screen --search \"关键词\"")
        lines.append("- dhgleaner screen --add \"1,3-5\"")
    return "\n".join(lines)


def _escapeCell(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )
