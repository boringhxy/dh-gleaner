"""方正 Founder rc-pub 开放 JSON API 解析器（散篇 harvest 用）。

适用于把目录托管在 ``publish.founderss.cn`` 方正发布平台的期刊，例如《现代情报》
（siteId=1084）。这类站点没有可直接解析的单期 HTML 目录页，而是两个开放 JSON 接口：

- ``getPeriodTree?siteId=``            → 年 → 期 → periodId 树
- ``getArticlesByPeriodicalIdGroupByColumn/{pid}?siteId=`` → 按栏目分组的文章（含中文摘要 summary）

因此本解析器只实现 ``harvestYear``（按年枚举全目录），``parseCurrentIssue`` 不适用。
接口本身已内联摘要，无需逐篇再抓详情页。

红线：只读开放接口；401/403/412 由 ``fetchJson`` 立即抛 ``FetchBlocked``（不绕过）；
逐期请求之间按 ``harvestDelay`` 限速。
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple

from ..http_util import fetchJson
from ..models import Article, IssueInfo
from ..textutil import cleanText
from .base import BaseParser

log = logging.getLogger(__name__)

FOUNDER_API = "https://www.publish.founderss.cn"


class FounderParser(BaseParser):
    """方正 Founder rc-pub JSON API 解析器（仅支持按年 harvest）。"""

    supportsHarvest = True

    def __init__(self, journalName: str, httpCfg: dict, journalCfg: Optional[dict] = None):
        super().__init__(journalName, httpCfg)
        cfg = journalCfg or {}
        self.siteId = cfg.get("siteId")
        self.referer = cfg.get("referer", "")
        self.apiBase = (cfg.get("founderApi") or FOUNDER_API).rstrip("/")
        self.harvestDelay = cfg.get("harvestDelay", self.harvestDelay)

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        raise NotImplementedError(
            f"《{self.journalName}》走方正 Founder JSON API，没有可解析的单期 HTML 目录页；"
            "请用 harvest 流程按年采集。"
        )

    def harvestYear(
        self, year: int, *, withAbstracts: bool = True
    ) -> Tuple[Optional[IssueInfo], List[Article]]:
        if not self.siteId:
            raise ValueError(f"《{self.journalName}》缺少 siteId 配置，无法调用方正接口")

        periods = self._periodIdsForYear(year)
        log.info("《%s》%d 年共 %d 期（方正 API）", self.journalName, year, len(periods))

        articles: List[Article] = []
        for issue, volume, periodId in periods:
            articles.extend(self._articlesOfPeriod(periodId, year, issue, volume))
            time.sleep(self.harvestDelay)

        return IssueInfo(year=year, volume=None, issue=0), articles

    # -- 内部 ---------------------------------------------------------------

    def _periodIdsForYear(self, year: int) -> List[Tuple[int, Optional[int], object]]:
        """getPeriodTree → 目标年的 (issue, volume, periodId) 列表，按期号升序。"""
        tree = fetchJson(
            f"{self.apiBase}/rc-pub/front/front-period/getPeriodTree?siteId={self.siteId}",
            self.userAgent,
            timeout=self.timeout,
            maxRetries=self.maxRetries,
            retryInterval=self.retryInterval,
            referer=self.referer,
        )
        periods: List[Tuple[int, Optional[int], object]] = []
        for group in tree.get("data") or []:
            for yearGroup in group.get("periods") or []:
                if yearGroup.get("year") != year:
                    continue
                for iss in yearGroup.get("periods") or []:
                    periods.append((int(iss.get("issue") or 0), iss.get("volume"), iss.get("id")))
        periods.sort(key=lambda item: item[0])
        return periods

    def _articlesOfPeriod(
        self, periodId: object, year: int, issue: int, volume: Optional[int]
    ) -> List[Article]:
        data = fetchJson(
            f"{self.apiBase}/rc-pub/front/front-article/"
            f"getArticlesByPeriodicalIdGroupByColumn/{periodId}?siteId={self.siteId}",
            self.userAgent,
            timeout=self.timeout,
            maxRetries=self.maxRetries,
            retryInterval=self.retryInterval,
            referer=self.referer,
        )
        articles: List[Article] = []
        for column in data.get("data") or []:
            columnName = cleanText(column.get("column") or "")
            for item in column.get("content") or []:
                article = self._oneArticle(item, year, issue, volume, columnName)
                if article:
                    articles.append(article)
        return articles

    def _oneArticle(
        self, item: dict, year: int, issue: int, volume: Optional[int], columnName: str
    ) -> Optional[Article]:
        title = cleanText(item.get("resName") or "")
        if not title:
            return None
        doi = (item.get("doi") or "").strip()
        rawVolume = item.get("volume") or volume
        articleVolume = int(rawVolume) if str(rawVolume or "").isdigit() else None
        articleIssue = int(item.get("issue") or issue)
        articleYear = int(item.get("year") or year)
        authors = [a.strip() for a in re.split(r"[;；]", item.get("authors") or "") if a.strip()]
        issueDisplay = (
            f"{articleYear}, {articleVolume}({articleIssue})"
            if articleVolume
            else f"{articleYear}({articleIssue})"
        )
        return Article(
            journal=self.journalName,
            year=articleYear,
            volume=articleVolume,
            issue=articleIssue,
            section=cleanText(item.get("part") or columnName or ""),
            title=title,
            authors=authors,
            abstract=cleanText(item.get("summary") or ""),
            keywords=cleanText(item.get("keyword") or ""),
            startPage=int(item.get("firstPageNum") or 0),
            endPage=int(item.get("lastPageNum") or 0),
            doi=doi,
            issueDisplay=issueDisplay,
            sourceType="harvest",
            articleUrl=f"https://doi.org/{doi}" if doi else "",
        )
