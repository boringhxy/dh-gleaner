"""通用 Magtech/Journy 期刊目录解析器。

适用于与玛格泰克/期刊数据管理平台相近的目录页，例如《图书馆论坛》、
《图书馆杂志》等。解析器尽量只提取筛选所需的元数据和摘要；PDF
仍只在 import 阶段处理。
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..models import Article, IssueInfo
from .base import BaseParser

log = logging.getLogger(__name__)


class MagtechParser(BaseParser):
    """通用 Magtech/Journy 目录页解析器。"""

    def __init__(self, journalName: str, httpCfg: dict, baseUrl: str = ""):
        super().__init__(journalName, httpCfg)
        self.baseUrl = baseUrl.rstrip("/")

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
            for pager in range(1, int(totalMatch.group(1)) + 1):
                pages.add(self._channelPageUrl(sourceUrl, str(pager), channelId, year))
        return sorted(pages, key=self._pageSortKey)

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
            if len(groups) >= 4 and re.match(r"\d{4}-\d{2}-\d{2}", groups[3]):
                return IssueInfo(year=int(groups[0]), volume=int(groups[1]), issue=int(groups[2]), publishDate=groups[3])
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
