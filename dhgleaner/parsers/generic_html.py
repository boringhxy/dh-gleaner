"""通用网页目录解析器。

用于缺少稳定期刊系统的网页：在用户提供 --url 时尽量从页面中抽取
文章标题和链接。摘要/PDF 通常为空，后续导入时按元数据降级。
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Article, IssueInfo
from ..textutil import isBlacklistedTitle, isNavigationTitle
from .base import BaseParser

log = logging.getLogger(__name__)

#: 站点外壳的标签名。注意不含 ``header``——WordPress 文章标题就包在
#: ``header.entry-header`` 里，把 header 一并禁掉会把真实条目全删了。
_CHROME_TAGS = frozenset({"nav", "footer", "aside"})

#: 站点外壳的 class **整词**匹配（按空格切分后逐个比对，不做子串匹配）。
#: 用整词是因为子串会把 ``entry-header`` 这类真实条目容器一起误杀。
#: 也别把 ``cryout`` 这类主题主内容容器放进来 —— DHCN 的整篇文章列表就套在它下面。
_CHROME_CLASS_TOKENS = frozenset({
    "menu", "menu-item", "sub-menu", "side-menu", "nav-menu", "widget", "widget-area",
    "site-header", "site-header-inside", "breadcrumb", "breadcrumbs",
    "pagination", "post-continue-container", "tag", "tags", "share", "social",
})


class GenericHtmlParser(BaseParser):
    """从普通网页中尽量抽取文章链接。"""

    def __init__(self, journalName: str, httpCfg: dict, baseUrl: str = "", options: dict | None = None):
        super().__init__(journalName, httpCfg)
        self.baseUrl = baseUrl.rstrip("/")
        self.options = options or {}

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")
        required = self.options.get("requiredPageText", [])
        pageText = soup.get_text(" ", strip=True)
        missing = [text for text in required if text not in pageText]
        if missing:
            raise ValueError(f"页面缺少必要文本: {', '.join(missing)}；疑似非目标页")
        issue = self._parseIssueInfo(soup)
        articles = self._parseArticles(soup, issue, self._pageTitle(soup))
        log.info("《%s》通用解析完成: %s, 共 %d 篇文章", self.journalName, issue.label(), len(articles))
        return issue, articles

    def _pageTitle(self, soup: BeautifulSoup) -> str:
        """页面主标题（通常是 h1 的刊名/期次名），它不是栏目名。"""
        h1 = soup.find("h1")
        return h1.get_text(" ", strip=True) if h1 else ""

    def _parseIssueInfo(self, soup: BeautifulSoup) -> IssueInfo:
        text = soup.get_text(" ", strip=True)
        # 「2025年4期」「2025年 第4期」「2025年第04期」都要认——DHCN 各期页的 h1 写作
        # 「《数字人文》2025年第4期」，不接受「第」就会整期退化成 issue=0，条目缺期号。
        m = re.search(r"(20\d{2})年\s*第?\s*0*(\d{1,2})\s*期", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=None, issue=int(m.group(2)))
        m = re.search(r"(20\d{2})年[，,\s]*第(\d+)卷[，,\s]*第(\d+)期", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=int(m.group(2)), issue=int(m.group(3)))
        m = re.search(r"(20\d{2})", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=None, issue=0)
        return IssueInfo(year=0, volume=None, issue=0)

    def _parseArticles(self, soup: BeautifulSoup, issue: IssueInfo, pageTitle: str = "") -> List[Article]:
        articles: List[Article] = []
        seen = set()
        roots = self._candidateRoots(soup)
        # 配置了 containerSelectors 就等于人工认定「这些容器里只有条目」，
        # 不再用 titleKeywords 二次筛——否则《数字人文》各期里不含
        # 「数字人文/数据/历史/文献」字样的题名（如《基于改进YOLOv8的刺绣动态检测与分类研究》）会被整篇丢掉。
        requireKeyword = not self.options.get("containerSelectors")
        for root in roots:
            for a in root.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                href = self._absUrl(a.get("href", ""))
                if self._isSiteChrome(a) or not self._looksLikeArticleTitle(title, href, requireKeyword):
                    continue
                key = (re.sub(r"\s+", "", title), href)
                if key in seen:
                    continue
                seen.add(key)
                section = self._nearestSection(a, pageTitle)
                articles.append(Article(
                    journal=self.journalName,
                    year=issue.year,
                    volume=issue.volume,
                    issue=issue.issue,
                    section=section,
                    title=title,
                    authors=[],
                    abstract="",
                    sourceType=self.options.get("sourceType", "issue"),
                    sourceNote=self.options.get("sourceNote", ""),
                    articleUrl=href,
                    pdfUrl="",
                    pdfSize="",
                    publishDate=issue.publishDate,
                ))
        return articles

    def _isSiteChrome(self, a) -> bool:
        """链接是否挂在导航菜单、页头页脚、标签云这类站点外壳里。"""
        for parent in a.parents:
            if parent.name in _CHROME_TAGS:
                return True
            if _CHROME_CLASS_TOKENS.intersection(parent.get("class") or []):
                return True
        return False

    def _candidateRoots(self, soup: BeautifulSoup):
        selectors = self.options.get("containerSelectors", [])
        roots = []
        for selector in selectors:
            roots.extend(soup.select(selector))
        return roots or [soup.body or soup]

    def _looksLikeArticleTitle(self, title: str, href: str = "", requireKeyword: bool = True) -> bool:
        title = re.sub(r"\s+", " ", title or "").strip()
        if len(title) < int(self.options.get("minTitleLength", 8)) or len(title) > int(self.options.get("maxTitleLength", 120)):
            return False
        if isNavigationTitle(title) or isBlacklistedTitle(title, self.options.get("titleBlacklist", [])):
            return False
        if not self._allowedDomain(href):
            return False
        keywords = self.options.get("titleKeywords") if requireKeyword else None
        if keywords:
            return any(keyword in title for keyword in keywords)
        if not requireKeyword:
            return True
        return any(ch in title for ch in "研究数字人文图书馆文献数据历史") or "DH" in title.upper()

    def _allowedDomain(self, href: str) -> bool:
        allowed = self.options.get("allowedDomains", [])
        if not allowed:
            return True
        host = urlparse(href).netloc.lower()
        return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed)

    def _nearestSection(self, a, pageTitle: str = "") -> str:
        """条目往前找最近的标题当栏目名。

        WordPress 式「每条一个 h2 标题」的清单页里，前一个 h2 是**上一条的题名**而不是栏目，
        直接拿来会把整列错位一格。所以只认「不带链接、且不是页面主标题」的标题。
        """
        heading = None
        for parent in a.parents:
            if not getattr(parent, "find_previous", None):
                continue
            heading = parent.find_previous(["h1", "h2", "h3", "h4"])
            if heading:
                break
        while heading is not None:
            text = heading.get_text(" ", strip=True)
            if self._isSectionHeading(heading, a, text, pageTitle):
                return text
            heading = heading.find_previous(["h1", "h2", "h3", "h4"])
        return ""

    def _isSectionHeading(self, heading, a, text: str, pageTitle: str) -> bool:
        if not text or text == self.journalName or len(text) > 40:
            return False
        if pageTitle and text == pageTitle:
            return False
        if heading in list(a.parents):
            return False
        return heading.find("a", href=True) is None

    def _absUrl(self, href: str) -> str:
        if href.startswith("http"):
            return href
        base = self.baseUrl
        if not base:
            return href
        parsed = urlparse(base)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
        return urljoin(root, href)
