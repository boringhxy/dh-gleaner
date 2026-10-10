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
from .base import BaseParser

log = logging.getLogger(__name__)


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
        articles = self._parseArticles(soup, issue)
        log.info("《%s》通用解析完成: %s, 共 %d 篇文章", self.journalName, issue.label(), len(articles))
        return issue, articles

    def _parseIssueInfo(self, soup: BeautifulSoup) -> IssueInfo:
        text = soup.get_text(" ", strip=True)
        m = re.search(r"(20\d{2})年\s*0*(\d+)期", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=None, issue=int(m.group(2)))
        m = re.search(r"(20\d{2})年[，,\s]*第(\d+)卷[，,\s]*第(\d+)期", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=int(m.group(2)), issue=int(m.group(3)))
        m = re.search(r"(20\d{2})", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=None, issue=0)
        return IssueInfo(year=0, volume=None, issue=0)

    def _parseArticles(self, soup: BeautifulSoup, issue: IssueInfo) -> List[Article]:
        articles: List[Article] = []
        seen = set()
        roots = self._candidateRoots(soup)
        for root in roots:
            for a in root.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                href = self._absUrl(a.get("href", ""))
                if not self._looksLikeArticleTitle(title, href):
                    continue
                key = (re.sub(r"\s+", "", title), href)
                if key in seen:
                    continue
                seen.add(key)
                section = self._nearestSection(a)
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

    def _candidateRoots(self, soup: BeautifulSoup):
        selectors = self.options.get("containerSelectors", [])
        roots = []
        for selector in selectors:
            roots.extend(soup.select(selector))
        return roots or [soup.body or soup]

    def _looksLikeArticleTitle(self, title: str, href: str = "") -> bool:
        title = re.sub(r"\s+", " ", title or "").strip()
        if len(title) < int(self.options.get("minTitleLength", 8)) or len(title) > int(self.options.get("maxTitleLength", 120)):
            return False
        badDefaults = {
            "首页", "投稿指南", "联系我们", "期刊介绍", "过刊浏览", "在线投稿", "下载中心", "更多", "English",
            "Read More", "More", "数据库", "精选期刊", "最新消息", "关于我们", "广告合作",
        }
        blacklist = set(self.options.get("titleBlacklist", [])) | badDefaults
        if title in blacklist:
            return False
        if any(bad.lower() in title.lower() for bad in blacklist if len(bad) >= 4):
            return False
        if not self._allowedDomain(href):
            return False
        keywords = self.options.get("titleKeywords")
        if keywords:
            return any(keyword in title for keyword in keywords)
        return any(ch in title for ch in "研究数字人文图书馆文献数据历史") or "DH" in title.upper()

    def _allowedDomain(self, href: str) -> bool:
        allowed = self.options.get("allowedDomains", [])
        if not allowed:
            return True
        host = urlparse(href).netloc.lower()
        return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed)

    def _nearestSection(self, a) -> str:
        for parent in a.parents:
            if not getattr(parent, "find_previous", None):
                continue
            heading = parent.find_previous(["h1", "h2", "h3", "h4"])
            if heading:
                text = heading.get_text(" ", strip=True)
                if text and text != self.journalName and len(text) <= 40:
                    return text
        return ""

    def _absUrl(self, href: str) -> str:
        if href.startswith("http"):
            return href
        base = self.baseUrl
        if not base:
            return href
        parsed = urlparse(base)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
        return urljoin(root, href)
