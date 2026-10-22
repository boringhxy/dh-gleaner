"""JournalX（.NET aspx）期刊系统解析器（散篇 harvest 用）。

适用于 ``.../ch/reader/`` 结构的 JournalX 站点，例如《中国图书馆学报》(jlis)、
《国家图书馆学刊》(gtxk)、《数字图书馆论坛》(dlf)。两类页面：

- 列表  ``issue_list.aspx?year_id=YYYY&quarter_id=N`` → 每篇 3 个 ``<tr>``（题名 / 作者 / 年期页）
- 详情  ``view_abstract.aspx?file_no=NNNNNNNN``       → 中文摘要 / 中文关键词

列表页不含摘要，``harvestYear`` 在 ``withAbstracts`` 时逐篇抓详情补全。

红线：只读公开页；401/403/412 由 ``fetchHtml`` 立即抛 ``FetchBlocked``（不绕过）；
逐期/逐篇请求之间按 ``harvestDelay`` 限速。
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..http_util import FetchBlocked, FetchFailed, fetchHtml
from ..models import Article, IssueInfo
from ..textutil import cleanText, isFrontMatterTitle
from .base import BaseParser

log = logging.getLogger(__name__)

_ABS_RE = re.compile(r"中文摘要\s*[：:]\s*(.*?)(?:英文摘要|中文关键词|英文关键词|$)", re.S)
_KW_RE = re.compile(r"中文关键词\s*[：:]\s*(.*?)(?:英文关键词|英文摘要|DOI|基金|$)", re.S)
_PAGE_RE = re.compile(r"(20\d{2})\s*[,，]\s*(\d+)\s*\(\s*(\d+)\s*\)\s*:\s*(\d+)\s*-\s*(\d+)")
_ISSUE_RE = re.compile(r"(20\d{2})\s*[,，]\s*(\d+)\s*\(\s*(\d+)\s*\)")
_TITLE_HREF_RE = re.compile(r"view_abstract\.aspx\?file_no=")


def _titleLink(tr: Tag) -> Optional[Tag]:
    """这一行的题名链接；不是题名的 view_abstract 链接返回 None。

    必须和「取题名」用同一口径：jlis 的年期页行里也挂着一个 `view_abstract.aspx`
    链接，文本是「摘要」。按 href 判断就会把这一行当成下一篇文章的开头，扫不到卷期页。
    """
    link = tr.find("a", href=_TITLE_HREF_RE)
    if link is None:
        return None
    title = cleanText(link.get_text(" ", strip=True))
    if not title or title == "摘要" or "下载" in title:
        return None
    return link


class JournalXParser(BaseParser):
    """JournalX .NET aspx 解析器（支持单期解析与按年 harvest）。"""

    supportsHarvest = True

    def __init__(
        self,
        journalName: str,
        httpCfg: dict,
        baseUrl: str = "",
        journalCfg: Optional[dict] = None,
    ):
        super().__init__(journalName, httpCfg)
        cfg = journalCfg or {}
        base = baseUrl or cfg.get("url") or cfg.get("currentIssueUrl") or ""
        self.baseUrl = base.rstrip("/") + "/" if base else ""
        self.maxQuarter = int(cfg.get("maxQuarter", 12))
        self.harvestDelay = cfg.get("harvestDelay", self.harvestDelay)

    # -- 单期解析 ------------------------------------------------------------

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")
        articles = self._rows(soup, year=0, quarter=0)
        issue = self._issueFromArticles(articles)
        log.info("《%s》解析完成: %s, 共 %d 篇文章", self.journalName, issue.label(), len(articles))
        return issue, articles

    # -- 按年 harvest --------------------------------------------------------

    def harvestYear(
        self, year: int, *, withAbstracts: bool = True
    ) -> Tuple[Optional[IssueInfo], List[Article]]:
        if not self.baseUrl:
            raise ValueError(f"《{self.journalName}》缺少 reader 基址，无法枚举 JournalX 目录")

        articles: List[Article] = []
        emptyStreak = 0
        for quarter in range(1, self.maxQuarter + 1):
            url = f"{self.baseUrl}issue_list.aspx?year_id={year}&quarter_id={quarter}"
            try:
                html = self._fetch(url)
            except (FetchBlocked, FetchFailed) as e:
                log.info("《%s》%s 抓取失败，跳过: %s", self.journalName, url, e)
                emptyStreak += 1
                if emptyStreak >= 2:
                    break
                continue
            time.sleep(self.harvestDelay)

            rows = self._rows(BeautifulSoup(html, "lxml"), year=year, quarter=quarter)
            if not rows:
                emptyStreak += 1
                if emptyStreak >= 2:
                    break
                continue
            emptyStreak = 0

            if withAbstracts:
                self._fillAbstracts(rows)
            articles.extend(rows)

        log.info("《%s》%d 年 harvest 完成: %d 篇", self.journalName, year, len(articles))
        return IssueInfo(year=year, volume=None, issue=0), articles

    # -- 内部 ---------------------------------------------------------------

    def _fetch(self, url: str) -> str:
        return fetchHtml(
            url,
            self.userAgent,
            timeout=self.timeout,
            maxRetries=self.maxRetries,
            retryInterval=self.retryInterval,
        )

    def _fillAbstracts(self, articles: List[Article]) -> None:
        for article in articles:
            if not article.articleUrl:
                continue
            try:
                article.abstract, article.keywords = self._detail(article.articleUrl)
            except (FetchBlocked, FetchFailed) as e:
                log.debug("《%s》详情摘要抓取失败 %s: %s", self.journalName, article.articleUrl, e)
            time.sleep(self.harvestDelay)

    def _detail(self, url: str) -> Tuple[str, str]:
        """抓 view_abstract 详情页，返回 (中文摘要, 中文关键词)。

        个别页面会把摘要长句误排到「中文关键词」标签后；关键词应为短词列，
        若混入句号或过长则判为污染并丢弃（摘要不受影响，仍是 DH 匹配主信号）。
        """
        text = BeautifulSoup(self._fetch(url), "lxml").get_text(" ", strip=True)
        absMatch = _ABS_RE.search(text)
        kwMatch = _KW_RE.search(text)
        abstract = cleanText(absMatch.group(1)) if absMatch else ""
        keywords = cleanText(kwMatch.group(1)) if kwMatch else ""
        if keywords and ("。" in keywords or len(keywords) > 80):
            keywords = ""
        return abstract, keywords

    def _rows(self, soup: BeautifulSoup, year: int, quarter: int) -> List[Article]:
        """issue_list 页：每篇有题名链接（view_abstract?file_no=）；按 file_no 去重。

        作者与年期页都在题名行之后、下一个题名行之前的若干 tr 里，按行内容而不是行号判定
        （jlis 带页码，gtxk 仅 年,卷(期)）。
        """
        articles: List[Article] = []
        seen: set[str] = set()
        trs = soup.find_all("tr")
        for i, tr in enumerate(trs):
            if tr.find("tr"):  # 跳过嵌套表格的外层包裹 tr（gtxk 把整页目录套在大 tr 里）
                continue
            link = _titleLink(tr)
            title = cleanText(link.get_text(" ", strip=True)) if link else ""
            if not link:
                continue
            if isFrontMatterTitle(title):
                continue
            href = link.get("href", "")
            fileNoMatch = re.search(r"file_no=(\w+)", href)
            fileNo = fileNoMatch.group(1) if fileNoMatch else href
            if fileNo in seen:
                continue
            seen.add(fileNo)

            # 从题名行往后扫，遇到下一个题名行即停。此前是按 (i+1, i+2, i+3) 的
            # 固定行号取作者与年期页，等于假设「每篇恰好 3 个 tr」；站点多插一行
            # （作者单位、DOI）就会读到下一篇文章的年期页，把别人的卷期页挂到这篇上。
            authors: List[str] = []
            volume: Optional[int] = None
            issue = quarter
            startPage = endPage = 0
            issueDisplay = ""
            articleYear = year
            for row in trs[i + 1:]:
                if row.find("tr"):  # 嵌套表格的包裹行，整页文本会淹没判定
                    continue
                if _titleLink(row):
                    break
                if authors and volume is not None:  # 作者与年期页都齐了，不必再往后看
                    break
                text = row.get_text(" ", strip=True)
                if not text:
                    continue
                pageMatch = _PAGE_RE.search(text)
                issueMatch = None if pageMatch else _ISSUE_RE.search(text)
                if pageMatch or issueMatch:
                    if volume is not None:  # 已有年期页，后面的行不再覆盖
                        continue
                    matched = pageMatch or issueMatch
                    articleYear = int(matched.group(1))
                    volume, issue = int(matched.group(2)), int(matched.group(3))
                    if pageMatch:
                        startPage, endPage = int(pageMatch.group(4)), int(pageMatch.group(5))
                    issueDisplay = f"{articleYear}, {volume}({issue})"
                    continue
                if authors:  # 只认第一条非年期页行为作者，多插的说明行不当作者
                    continue
                authors = [a.strip() for a in re.split(r"[，,;；、\s]+", text) if a.strip()]

            articles.append(Article(
                journal=self.journalName,
                year=articleYear or year,
                volume=volume,
                issue=issue,
                title=title,
                authors=authors,
                startPage=startPage,
                endPage=endPage,
                issueDisplay=issueDisplay,
                sourceType="harvest",
                articleUrl=urljoin(self.baseUrl, href),
            ))
        return articles

    def _issueFromArticles(self, articles: List[Article]) -> IssueInfo:
        for article in articles:
            if article.year:
                return IssueInfo(year=article.year, volume=article.volume, issue=article.issue)
        return IssueInfo(year=0, volume=None, issue=0)
