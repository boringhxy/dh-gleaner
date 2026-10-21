"""散篇 harvest：按年枚举全目录 → DH 关键词打标 → 过滤 → 交给 service 落盘。

与 capture（单期 / 栏目）并列的第三种采集流程，面向「没有常设数字人文栏目、DH 内容
以散篇混在各栏目里」的图情/信息刊。红线与 capture 一致：只读公开页 / 开放 API，
**不写 Zotero、不下载 PDF**；逐期/逐篇请求由各解析器按 ``harvestDelay`` 限速。

本模块只做「取数据 + 打标 + 过滤 + 去重」，落盘（pending.json / review.md）交给
``service.captureHarvest``，因此与 capture 流程共用同一套 screen / import 下游。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from .capture import getParser
from .keywords import isDh, tagArticles
from .models import Article, IssueInfo
from .state import StateManager
from .textutil import isFrontMatterTitle

log = logging.getLogger(__name__)
_TZ = timezone(timedelta(hours=8))


def isHarvestJournal(journalCfg: dict) -> bool:
    """配置里显式标了 ``harvestOnly`` 的散篇期刊，才进入默认 harvest 轮转。"""
    return bool(journalCfg.get("harvestOnly"))


def harvestJournal(
    journalCfg: dict,
    httpCfg: dict,
    state: StateManager,
    *,
    year: int,
    withAbstracts: bool = True,
    dedupe: bool = False,
    dhOnly: bool = True,
) -> Tuple[Optional[IssueInfo], List[Article]]:
    """按年 harvest 单本期刊，返回 (期次标记, 文章列表)。

    每篇文章都会被打上 dhMatched / histAiMatched 双标签；``dhOnly=True``（默认）时
    只保留命中任一表的 DH 散篇，``False`` 时保留全目录（仍带标签）。
    """
    name = journalCfg["name"]
    parserName = journalCfg["parser"]
    parser = getParser(parserName, name, httpCfg, journalCfg)
    if not getattr(parser, "supportsHarvest", False):
        log.error("《%s》解析器 %s 不支持按年 harvest", name, parserName)
        return None, []

    try:
        issue, articles = parser.harvestYear(year, withAbstracts=withAbstracts)
    except Exception as e:  # noqa: BLE001 — 单刊失败不应中断整轮 harvest
        log.error("《%s》%d 年 harvest 失败: %s", name, year, e)
        return None, []

    articles = [a for a in articles if not isFrontMatterTitle(a.title)]
    tagArticles(articles)
    catalogCount = len(articles)
    if dhOnly:
        articles = [a for a in articles if isDh(a)]
    if dedupe:
        articles = [a for a in articles if not state.isArticleProcessed(name, a.articleKey())]

    state.updateLastCheck(name)
    nowIso = datetime.now(_TZ).isoformat(timespec="seconds")
    for article in articles:
        article.capturedAt = nowIso

    log.info(
        "《%s》%d 年 harvest: 全目录 %d 篇 → 保留 %d 篇（dhOnly=%s）",
        name, year, catalogCount, len(articles), dhOnly,
    )
    return issue, articles


def harvestAll(
    journalsCfg: list,
    httpCfg: dict,
    state: StateManager,
    *,
    year: int,
    journalName: str = "",
    withAbstracts: bool = True,
    dedupe: bool = False,
    dhOnly: bool = True,
) -> List[Tuple[str, Optional[IssueInfo], List[Article]]]:
    """harvest 一批期刊。

    - 指定 ``journalName`` 时只 harvest 该刊（须支持 harvest）；
    - 否则 harvest 配置中所有标了 ``harvestOnly`` 的散篇期刊。
    """
    results: List[Tuple[str, Optional[IssueInfo], List[Article]]] = []
    for journalCfg in journalsCfg:
        name = journalCfg["name"]
        if journalName:
            if name != journalName:
                continue
        elif not isHarvestJournal(journalCfg):
            continue
        issue, articles = harvestJournal(
            journalCfg, httpCfg, state,
            year=year, withAbstracts=withAbstracts, dedupe=dedupe, dhOnly=dhOnly,
        )
        results.append((name, issue, articles))
    return results
