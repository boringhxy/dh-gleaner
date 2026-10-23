"""通用 Magtech/Journy 期刊目录解析器。

适用于与玛格泰克/期刊数据管理平台相近的目录页，例如《图书馆论坛》、
《图书馆杂志》等。解析器尽量只提取筛选所需的元数据和摘要；PDF
仍只在 import 阶段处理。
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..http_util import FetchBlocked, FetchFailed, fetchHtml
from ..models import Article, IssueInfo
from ..textutil import cleanText, normalizeDate
from .base import BaseParser

log = logging.getLogger(__name__)

# harvest（按年枚举 volumn_N.shtml）用到的皮肤正则。仅 harvestYear 路径使用，
# 不影响经典 noselectrow 皮肤的当期/栏目解析。
_LIWEN_ISSUE_RE = re.compile(r"(20\d{2})\s*Vol\.?\s*(\d+)\s*\(\s*(\d+)\s*\)")
_LIWEN_PAGE_RE = re.compile(r"\)\s*:\s*(\d+)\s*-\s*(\d+)")
_DQML_URL_RE = re.compile(r"/CN/Y(\d{4})/V(\d+)/I(\d+)/")
_DQML_PAGE_RE = re.compile(r"(20\d{2})\s*[,，]\s*(\d+)\s*\(\s*(\d+)\s*\)\s*:\s*(\d+)\s*-\s*(\d+)")
_DQML_DOI_RE = re.compile(r"doi[:：]\s*(10\.\d{4,}/\S+)")
_VOLNUM_RE = re.compile(r"volumn_(\d+)\.shtml")
_ZHAIYAO_RE = re.compile(r"摘要[：:]\s*(.*?)(?:Abstract[：:]|\bAbstract\b|$)", re.S)


class MagtechParser(BaseParser):
    """通用 Magtech/Journy 目录页解析器。"""

    supportsHarvest = True

    def __init__(
        self,
        journalName: str,
        httpCfg: dict,
        baseUrl: str = "",
        journalCfg: Optional[dict] = None,
    ):
        super().__init__(journalName, httpCfg)
        self.baseUrl = baseUrl.rstrip("/")
        cfg = journalCfg or {}
        self.archivePath = cfg.get("archivePath", "/CN/article/showOldVolumn.do")
        self.archiveUrl = cfg.get("archiveUrl", "")
        self.maxScan = int(cfg.get("maxScan", 40))
        #: 栏目分页封顶。「共 N 页」是从页面文本正则抠出来的，抠错一位数就会
        #: 变成上万个请求，因此必须有硬上限；真需要更深的栏目在配置里调大。
        self.maxChannelPages = int(cfg.get("maxChannelPages", 50))
        #: 上一次 discoverChannelPageUrls 是否真的截断过分页。capture 侧靠它判断清单
        #: 完整性，不用拿「页数 == 上限」去猜——正好等于上限的完整栏目会被误判成缺页。
        self.channelPagesTruncated = False
        self.harvestDelay = cfg.get("harvestDelay", self.harvestDelay)

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")
        issue = self._parseIssueInfo(soup)
        articles = self._parseArticles(soup, issue)
        log.info("《%s》解析完成: %s, 共 %d 篇文章", self.journalName, issue.label(), len(articles))
        return issue, articles

    def parseChannelPage(self, html: str, channelName: str = "") -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")
        channel = channelName or self._channelName(soup) or "栏目"
        issue = IssueInfo(year=0, volume=None, issue=0)
        articles = self._parseArticles(soup, issue, sourceType="channel", channelName=channel)
        log.info("《%s》栏目《%s》解析完成: 共 %d 篇文章", self.journalName, channel, len(articles))
        return issue, articles

    def discoverChannelPageUrls(self, html: str, sourceUrl: str) -> List[str]:
        pages = set()
        truncated = False
        parsedSource = urlparse(sourceUrl)
        sourceQs = parse_qs(parsedSource.query)
        if sourceQs.get("id"):
            pages.add(self._channelPageUrl(sourceUrl, sourceQs.get("pager", ["1"])[0], sourceQs["id"][0], sourceQs.get("year", ["0"])[0]))
        else:
            pages.add(sourceUrl)
        for pager, channelId, year in re.findall(r"changePage\('?(\d+)'?,\s*'?(\d+)'?,\s*'?(\d+)'?\)", html):
            if int(pager) <= 0:
                continue
            pages.add(self._channelPageUrl(sourceUrl, pager, channelId, year))
        parsed = urlparse(sourceUrl)
        qs = parse_qs(parsed.query)
        channelId = (qs.get("id") or [""])[0]
        year = (qs.get("year") or ["0"])[0]
        totalMatch = re.search(r"共\s*(\d+)\s*页", html)
        if channelId and totalMatch:
            total = int(totalMatch.group(1))
            if total > self.maxChannelPages:
                truncated = True
                # 先在这里折，不让 range() 真的展开出上万个 URL
                total = self.maxChannelPages
            for pager in range(1, total + 1):
                pages.add(self._channelPageUrl(sourceUrl, str(pager), channelId, year))
        pages = sorted(pages, key=self._pageSortKey)
        # 封顶必须作用在合并后的全集上：`changePage(...)` 那条分支收的是页面里真实存在的
        # 分页项（「每页 N 条」的下拉框就能列出几十个），完全绕开「共 N 页」分支的 clamp，
        # 只封后者等于上限形同虚设。
        if self.maxChannelPages and len(pages) > self.maxChannelPages:
            truncated = True
            pages = pages[: self.maxChannelPages]
        self.channelPagesTruncated = truncated
        if truncated:
            log.warning(
                "《%s》栏目分页超过上限 %d 页，只抓前 %d 页，清单可能不完整；"
                "若确实需要更深的分页，请在该刊配置里调大 maxChannelPages。",
                self.journalName,
                self.maxChannelPages,
                self.maxChannelPages,
            )
        return pages

    def _channelPageUrl(self, sourceUrl: str, pager: str, channelId: str, year: str) -> str:
        parsed = urlparse(sourceUrl)
        qs = parse_qs(parsed.query)
        qs["pager"] = [str(pager)]
        qs["id"] = [str(channelId)]
        qs["year"] = [str(year or "0")]
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    def _pageSortKey(self, url: str) -> tuple[int, str]:
        pager = (parse_qs(urlparse(url).query).get("pager") or ["1"])[0]
        try:
            return int(pager), url
        except ValueError:
            return 1, url

    def _channelName(self, soup: BeautifulSoup) -> str:
        node = soup.find(class_="item-columnName")
        return node.get_text(" ", strip=True) if node else ""

    def _parseIssueInfo(self, soup: BeautifulSoup) -> IssueInfo:
        text = soup.get_text(" ", strip=True)
        patterns = [
            r"(\d{4})年[，,\s]*第(\d+)卷[，,\s]*第(\d+)期.*?刊出日期[：:]\s*([\d-]+)",
            r"(\d{4})年[，,\s]*第(\d+)卷[，,\s]*第(\d+)期",
            r"(\d{4})[，,\s]+(\d+)\((\d+)\)",
            r"(\d{4})年\s*0*(\d+)期",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if not m:
                continue
            groups = m.groups()
            # 日期只在这里规范化一次，后面各分支都是复制 IssueInfo.publishDate
            publishDate = normalizeDate(groups[3]) if len(groups) >= 4 else ""
            if len(groups) >= 4 and publishDate:
                return IssueInfo(year=int(groups[0]), volume=int(groups[1]), issue=int(groups[2]), publishDate=publishDate)
            if len(groups) >= 3:
                return IssueInfo(year=int(groups[0]), volume=int(groups[1]), issue=int(groups[2]))
            if len(groups) == 2:
                return IssueInfo(year=int(groups[0]), volume=None, issue=int(groups[1]))
        log.warning("未能从页面提取期次信息，使用默认值")
        return IssueInfo(year=0, volume=None, issue=0)

    def _parseArticles(self, soup: BeautifulSoup, issue: IssueInfo, sourceType: str = "issue", channelName: str = "") -> List[Article]:
        articles: List[Article] = []
        currentSection = channelName or ""
        for el in soup.find_all(["div", "li"], class_=re.compile(r"wenzhanglanmu|noselectrow")):
            classes = " ".join(el.get("class", []))
            if "wenzhanglanmu" in classes:
                currentSection = self._sectionText(el)
                continue
            if "noselectrow" in classes:
                art = self._parseOneArticle(el, issue, currentSection, sourceType=sourceType)
                if art:
                    articles.append(art)
        return articles

    def _sectionText(self, el) -> str:
        a = el.find("a", attrs={"name": True})
        if a and a.get("name"):
            return a.get("name", "").strip()
        return el.get_text(" ", strip=True)

    def _parseOneArticle(self, block, issue: IssueInfo, section: str, sourceType: str = "issue") -> Article | None:
        articleId = self._articleId(block)
        titleA = self._titleLink(block)
        if not titleA:
            return None

        title = titleA.get_text(" ", strip=True)
        articleUrl = self._absUrl(titleA.get("href", ""))
        blockIssue = self._issueFromBlock(block, articleUrl, issue)
        authors = self._authors(block)
        startPage, endPage = self._pages(block)
        if not startPage and not endPage:
            startPage, endPage = self._pagesFromBlockIssue(block)
        abstract = self._abstract(block, articleId)
        pdfUrl, pdfSize = self._pdf(block, articleId)
        blockSection = self._blockSection(block) or section
        issueDisplay = self._issueDisplay(block, blockIssue)
        sourceNote = "栏目页抓取：每篇文章保留原站点年卷期；括号内期号可能为总期号" if sourceType == "channel" else ""

        return Article(
            journal=self.journalName,
            year=blockIssue.year,
            volume=blockIssue.volume,
            issue=blockIssue.issue,
            section=blockSection,
            title=title,
            authors=authors,
            abstract=abstract,
            startPage=startPage,
            endPage=endPage,
            issueDisplay=issueDisplay,
            totalIssue=blockIssue.issue if sourceType == "channel" and blockIssue.issue else None,
            sourceType=sourceType,
            sourceNote=sourceNote,
            articleUrl=articleUrl,
            pdfUrl=pdfUrl,
            pdfSize=pdfSize,
            publishDate=blockIssue.publishDate,
        )


    def _issueFromBlock(self, block, articleUrl: str, defaultIssue: IssueInfo) -> IssueInfo:
        text = block.get_text(" ", strip=True)
        m = re.search(r"(20\d{2})\s*[,，]\s*(\d+)\s*\(\s*(\d+)\s*\)", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=int(m.group(2)), issue=int(m.group(3)), publishDate=defaultIssue.publishDate)
        m = re.search(r"/CN/Y(20\d{2})/V(\d+)/I(\d+)", articleUrl)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=int(m.group(2)), issue=int(m.group(3)), publishDate=defaultIssue.publishDate)
        return defaultIssue

    def _issueDisplay(self, block, issue: IssueInfo) -> str:
        text = block.get_text(" ", strip=True)
        m = re.search(r"(20\d{2})\s*[,，]\s*(\d+)\s*\(\s*(\d+)\s*\)", text)
        if m:
            return f"{m.group(1)}, {m.group(2)}({m.group(3)})"
        if issue.year:
            return issue.label()
        return ""

    def _pagesFromBlockIssue(self, block) -> tuple[int, int]:
        text = block.get_text(" ", strip=True)
        m = re.search(r"20\d{2}\s*[,，]\s*\d+\s*\(\s*\d+\s*\)\s*:\s*(\d+)\s*-\s*(\d+)", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 0, 0

    def _articleId(self, block) -> str:
        bid = block.get("id", "")
        if bid.startswith("art"):
            return bid.replace("art", "", 1)
        inp = block.find("input", id=re.compile(r"thisart_"))
        if inp:
            return re.sub(r"^thisart_", "", inp.get("id", ""))
        return ""

    def _titleLink(self, block):
        candidates = [
            block.find("a", class_="biaoti"),
            block.select_one(".j-title-1 a[href]"),
            block.select_one(".j-title a[href]"),
            block.find("a", href=re.compile(r"/CN/Y\d{4}/")),
        ]
        for candidate in candidates:
            if candidate and candidate.get_text(" ", strip=True):
                return candidate
        return None

    def _authors(self, block) -> List[str]:
        nodes = [
            block.find("dd", class_="zuozhe"),
            block.find(class_="j-author"),
            block.find(class_=re.compile(r"author", re.I)),
        ]
        for node in nodes:
            if not node:
                continue
            text = node.get_text(" ", strip=True)
            authors = [a.strip() for a in re.split(r"[,，;；、]", text) if a.strip()]
            if authors:
                return authors
        return []

    def _pages(self, block) -> tuple[int, int]:
        text = block.get_text(" ", strip=True)
        patterns = [r":\s*(\d+)\s*-\s*(\d+)\s*\.", r"(\d+)\s*-\s*(\d+)页"]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return int(m.group(1)), int(m.group(2))
        return 0, 0

    def _abstract(self, block, articleId: str) -> str:
        nodes = []
        if articleId:
            nodes.append(block.find(id=f"Abstract{articleId}"))
        nodes.extend([block.find(class_="j-abstract"), block.find(class_=re.compile(r"abstract", re.I))])
        for node in nodes:
            if not node:
                continue
            text = node.get_text(" ", strip=True)
            if text and text not in {"摘要", "Abstract"}:
                return text
        return ""

    def _pdf(self, block, articleId: str) -> tuple[str, str]:
        pdfUrl = ""
        pdfSize = ""
        for a in block.find_all("a"):
            href = a.get("href", "")
            onclick = a.get("onclick", "")
            label = a.get_text(" ", strip=True)
            if "downloadArticleFile" in href or "download" in href.lower() or "PDF" in onclick or "PDF" in label.upper():
                if href and not href.startswith("javascript") and href != "#":
                    pdfUrl = self._absUrl(href)
                    break
                m = re.search(r"lsdy1\('PDF','?(\d+)'?", onclick)
                if m:
                    articleId = m.group(1)
                    break
        if not pdfUrl and articleId:
            pdfUrl = self._absUrl(f"/CN/article/downloadArticleFile.do?attachType=PDF&id={articleId}")
        m = re.search(r"(\d+\s*(?:KB|K|MB|M))", block.get_text(" ", strip=True), re.I)
        if m:
            raw = m.group(1).replace(" ", "").upper()
            num = re.match(r"(\d+)", raw).group(1)
            unit = "MB" if raw.endswith(("MB", "M")) else "KB"
            pdfSize = f"{num}{unit}"
        return pdfUrl, pdfSize

    def _blockSection(self, block) -> str:
        node = block.find(class_="j-column")
        return node.get_text(" ", strip=True) if node else ""

    def _absUrl(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("http"):
            return href
        base = self.baseUrl or ""
        if not base:
            return href
        parsed = urlparse(base)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
        return urljoin(root, href)

    # ------------------------------------------------------------------
    # harvest：按年枚举过刊 volumn_N.shtml（散篇采集用）。
    # 这段逻辑只在 harvestYear 路径触发，经典 noselectrow 皮肤的当期/栏目解析不受影响。
    # ------------------------------------------------------------------

    def harvestYear(
        self, year: int, *, withAbstracts: bool = True
    ) -> Tuple[Optional[IssueInfo], List[Article]]:
        if not self.baseUrl:
            raise ValueError(f"《{self.journalName}》缺少 baseUrl，无法枚举 magtech 过刊页")

        archiveUrl = self.archiveUrl or (self.baseUrl + self.archivePath)
        archiveHtml = self._fetch(archiveUrl)
        volNums = sorted({int(n) for n in _VOLNUM_RE.findall(archiveHtml)}, reverse=True)
        log.info("《%s》过刊页发现 %d 个 volumn，按年 harvest %d", self.journalName, len(volNums), year)

        articles: List[Article] = []
        olderStreak = 0
        for volNum in volNums[: self.maxScan]:
            vurl = f"{self.baseUrl}/CN/volumn/volumn_{volNum}.shtml"
            try:
                vhtml = self._fetch(vurl)
            except (FetchBlocked, FetchFailed) as e:
                log.info("《%s》volumn_%d 抓取失败，跳过: %s", self.journalName, volNum, e)
                continue
            time.sleep(self.harvestDelay)

            parsed = self._parseVolumnPage(BeautifulSoup(vhtml, "lxml"))
            parsed = [a for a in parsed if (a.title or "").strip()]
            if not parsed:
                continue

            volYear = max((a.year or 0) for a in parsed)
            if volYear == 0:
                volYear = self._parseIssueInfo(BeautifulSoup(vhtml, "lxml")).year
            if volYear > year:
                continue
            if volYear < year:
                olderStreak += 1
                if olderStreak >= 3:  # volumn 编号倒序≈时间倒序，连续 3 期更老即停
                    break
                continue
            olderStreak = 0

            parsed = [a for a in parsed if (a.year or year) == year]
            for article in parsed:
                if not article.year:
                    article.year = year
            if withAbstracts:
                self._fillHarvestAbstracts(parsed)
            articles.extend(parsed)

        log.info("《%s》%d 年 harvest 完成: %d 篇", self.journalName, year, len(articles))
        return IssueInfo(year=year, volume=None, issue=0), articles

    def _parseVolumnPage(self, soup: BeautifulSoup) -> List[Article]:
        """自动识别三种 magtech 皮肤：ul.lunwen / div.dqml / 经典 noselectrow。"""
        if soup.find("ul", class_="lunwen"):
            return self._parseLunwenList(soup)
        if soup.find("div", class_="dqml"):
            return self._parseDqmlList(soup)
        issue = self._parseIssueInfo(soup)
        return self._parseArticles(soup, issue, sourceType="harvest")

    def _fillHarvestAbstracts(self, articles: List[Article]) -> None:
        """lunwen/dqml 皮肤列表页无内联摘要，逐篇抓详情页补全（经典皮肤已有摘要则跳过）。"""
        for article in articles:
            if article.abstract or not article.articleUrl:
                continue
            try:
                article.abstract = self._detailAbstractZh(article.articleUrl)
            except (FetchBlocked, FetchFailed) as e:
                log.debug("《%s》详情摘要抓取失败 %s: %s", self.journalName, article.articleUrl, e)
            time.sleep(self.harvestDelay)

    def _detailAbstractZh(self, url: str) -> str:
        """抓详情页 div#zhaiyao 所在 panel 的 .panel-body，取「摘要：」到「Abstract」之间的中文摘要。

        没有 zhaiyao 面板或面板里没有「摘要：」标记（如专题引言、无摘要的编者按）时返回空串，
        避免把「引用本文…导出引用管理器」这类页脚误当摘要。
        """
        soup = BeautifulSoup(self._fetch(url), "lxml")
        head = soup.find("div", id="zhaiyao") or soup.find("a", id="abstract")
        panel = head.find_parent("div", class_="panel") if head else None
        body = panel.find("div", class_="panel-body") if panel else None
        if body is None:
            return ""
        text = body.get_text(" ", strip=True)
        match = _ZHAIYAO_RE.search(text)
        if not match:
            return ""
        return cleanText(re.sub(r"引用本文.*$", "", match.group(1), flags=re.S))

    def _fetch(self, url: str) -> str:
        return fetchHtml(
            url,
            self.userAgent,
            timeout=self.timeout,
            maxRetries=self.maxRetries,
            retryInterval=self.retryInterval,
        )

    def _parseLunwenList(self, soup: BeautifulSoup) -> List[Article]:
        """ul.lunwen 皮肤（情报科学等）：每个 <ul class='lunwen'> 是一篇文章。"""
        articles: List[Article] = []
        for ul in soup.find_all("ul", class_="lunwen"):
            current: Optional[Article] = None
            for li in ul.find_all("li", recursive=False):
                classes = " ".join(li.get("class", []))
                if "biaoti" in classes:
                    anchor = li.find("a", href=True)
                    title = cleanText((anchor or li).get_text(" ", strip=True))
                    href = anchor.get("href", "") if anchor else ""
                    current = Article(
                        journal=self.journalName,
                        year=0,
                        volume=None,
                        issue=0,
                        title=title,
                        sourceType="harvest",
                        articleUrl=self._absUrl(href),
                    )
                    articles.append(current)
                elif current is None:
                    continue
                elif "zuozhe" in classes:
                    current.authors = [
                        a.strip() for a in re.split(r"[,，;；、]", li.get_text(" ", strip=True)) if a.strip()
                    ]
                elif not classes:
                    text = li.get_text(" ", strip=True)
                    issueMatch = _LIWEN_ISSUE_RE.search(text)
                    if issueMatch:
                        current.year = int(issueMatch.group(1))
                        current.volume = int(issueMatch.group(2))
                        current.issue = int(issueMatch.group(3))
                        current.issueDisplay = f"{issueMatch.group(1)}, {issueMatch.group(2)}({issueMatch.group(3)})"
                    pageMatch = _LIWEN_PAGE_RE.search(text)
                    if pageMatch:
                        current.startPage = int(pageMatch.group(1))
                        current.endPage = int(pageMatch.group(2))
        return [a for a in articles if (a.title or "").strip()]

    def _parseDqmlList(self, soup: BeautifulSoup) -> List[Article]:
        """div.dqml 皮肤（图书情报知识 / 信息资源管理学报等 whu 站）：每篇一个 div.dqml。

        题名链接两种形态：卷首语 /CN/Y2026/V43/I3/1（年卷期在 URL 里），正文用 DOI 式
        /CN/10.13366/j.dik.2026.03.006（年卷期改从 dqml_wzn「作者 2026, 43 (3): 6-15.」取）。
        doi.org 锚、摘要/PDF 锚都不含 /CN/ 路径，故按「首个 /CN/ 且非摘要/PDF 的锚」取题名。
        """
        articles: List[Article] = []
        for block in soup.find_all("div", class_="dqml"):
            anchor = None
            for candidate in block.find_all("a"):
                href = candidate.get("href", "")
                text = candidate.get_text(" ", strip=True)
                if "/CN/" not in href or text in ("摘要", "PDF"):
                    continue
                anchor = candidate
                break
            if not anchor:
                continue
            title = cleanText(anchor.get_text(" ", strip=True))
            if not title:
                continue
            url = self._absUrl(anchor.get("href", ""))

            year = 0
            volume: Optional[int] = None
            issue = 0
            startPage = endPage = 0
            issueDisplay = ""
            urlMatch = _DQML_URL_RE.search(url)
            if urlMatch:
                year, volume, issue = int(urlMatch.group(1)), int(urlMatch.group(2)), int(urlMatch.group(3))
                issueDisplay = f"{year}, {volume}({issue})"

            authors: List[str] = []
            doi = ""
            wzText = block.find("div", class_="dqml_wzn")
            if wzText:
                wtext = wzText.get_text(" ", strip=True)
                pageMatch = _DQML_PAGE_RE.search(wtext)
                if pageMatch:
                    startPage, endPage = int(pageMatch.group(4)), int(pageMatch.group(5))
                    if not year:
                        year, volume, issue = int(pageMatch.group(1)), int(pageMatch.group(2)), int(pageMatch.group(3))
                        issueDisplay = f"{year}, {volume}({issue})"
                doiMatch = _DQML_DOI_RE.search(wtext)
                if doiMatch:
                    doi = doiMatch.group(1).rstrip(".")
                authorText = re.split(r"20\d{2}\s*[,，]", wtext, maxsplit=1)[0]
                authors = [
                    a.strip() for a in re.split(r"[，,;；、\s]+", authorText)
                    if a.strip() and a.strip() not in ("摘要", "PDF")
                ]

            articles.append(Article(
                journal=self.journalName,
                year=year,
                volume=volume,
                issue=issue,
                title=title,
                authors=authors,
                doi=doi,
                startPage=startPage,
                endPage=endPage,
                issueDisplay=issueDisplay,
                sourceType="harvest",
                articleUrl=url,
            ))
        return articles
