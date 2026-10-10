"""CNKI cbpt 解析器 — 《数字人文》(szrw.cbpt.cnki.net)。

HTML 结构要点（已实测）：
- 真实首页: /WKC/WebPublication/index.aspx?mid=SZRW （根路径会 meta refresh 重定向）
- 栏目标记: <h1>栏目名</h1>（首个 h1 是期刊名"数字人文"，需跳过）
- 文章列表: <ul class="column_contbox_zxlist"><li>...</li></ul>
- 标题:     <h3><a href="../WebPublication/paperDigest.aspx?paperID={UUID}">标题</a></h3>
- 作者:     <samp>周墨钦;王宏苏;...;</samp>（分号分隔，末尾有分号）
- 年期页:   <span>2025年04期  1-21页  ...</span>
- PDF下载:  <a href="../WebPublication/kbDownload.aspx?fn=SZRW202504001">下载</a> 3542K
- 摘要:     详情页(paperDigest.aspx)需验证码，通常无法自动获取 → 留空降级

注意: 《数字人文》无卷号(volume)，期次标签格式为 {年}-No{期}。
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Article, IssueInfo
from .base import BaseParser

log = logging.getLogger(__name__)


class CnkiCbptParser(BaseParser):
    """《数字人文》解析器 — CNKI 采编平台(cbpt)。"""

    BASE_URL = "https://szrw.cbpt.cnki.net/WKC/WebPublication/"

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")

        issue = self._parseIssueInfo(soup)
        articles = self._parseArticles(soup, issue)

        log.info(
            "《数字人文》解析完成: %s, 共 %d 篇文章",
            issue.label(),
            len(articles),
        )
        return issue, articles

    def _parseIssueInfo(self, soup: BeautifulSoup) -> IssueInfo:
        """从页面文本提取年期信息。《数字人文》无卷号。"""
        text = soup.get_text(" ", strip=True)
        # 匹配 "2025年04期"
        m = re.search(r"(\d{4})年\s*0*(\d+)期", text)
        if m:
            return IssueInfo(year=int(m.group(1)), volume=None, issue=int(m.group(2)))
        log.warning("未能从页面提取期次信息，使用默认值")
        return IssueInfo(year=0, issue=0)

    def _parseArticles(
        self, soup: BeautifulSoup, issue: IssueInfo
    ) -> List[Article]:
        """解析文章列表，跟踪当前栏目。"""
        articles: List[Article] = []
        currentSection = ""
        journalName = self.journalName  # "数字人文"

        # 按 DOM 顺序遍历 h1 和 ul.column_contbox_zxlist
        for el in soup.find_all(["h1", "ul"]):
            if el.name == "h1":
                title = el.get_text(strip=True)
                # 跳过期刊名本身
                if title and title != journalName and len(title) < 30:
                    currentSection = title
                    log.debug("进入栏目: %s", currentSection)
            elif el.name == "ul" and "column_contbox_zxlist" in " ".join(
                el.get("class", [])
            ):
                for li in el.find_all("li", recursive=False):
                    art = self._parseOneArticle(li, issue, currentSection)
                    if art:
                        articles.append(art)

        return articles

    def _parseOneArticle(self, li, issue: IssueInfo, section: str) -> Optional[Article]:
        """解析单篇文章 <li>；缺少标题/链接时返回 None。"""
        # 标题与链接
        titleA = li.find("a", href=re.compile(r"paperDigest"))
        if not titleA:
            return None
        title = titleA.get_text(strip=True)
        articleUrl = self._absUrl(titleA.get("href", ""))

        # 作者: <samp>周墨钦;王宏苏;...;</samp>
        authors = []
        samp = li.find("samp")
        if samp:
            authorText = samp.get_text(strip=True)
            authors = [a.strip() for a in authorText.split(";") if a.strip()]

        # 年期页 + 下载: <span>2025年04期  1-21页 ... 下载 ... 3542K</span>
        span = li.find("span")
        startPage, endPage = 0, 0
        pdfUrl = ""
        pdfSize = ""
        if span:
            spanText = span.get_text(" ", strip=True)
            # 页码
            pm = re.search(r"(\d+)-(\d+)页", spanText)
            if pm:
                startPage, endPage = int(pm.group(1)), int(pm.group(2))
            # PDF下载链接
            dlA = span.find("a", href=re.compile(r"kbDownload"))
            if dlA:
                pdfUrl = self._absUrl(dlA.get("href", ""))
                # 大小: "下载 3542K"
                sm = re.search(r"(\d+)\s*K", spanText)
                if sm:
                    pdfSize = f"{sm.group(1)}KB"

        return Article(
            journal=self.journalName,
            year=issue.year,
            volume=None,  # 《数字人文》无卷号
            issue=issue.issue,
            section=section,
            title=title,
            authors=authors,
            abstract="",  # 详情页需验证码，留空降级
            startPage=startPage,
            endPage=endPage,
            articleUrl=articleUrl,
            pdfUrl=pdfUrl,
            pdfSize=pdfSize,
            publishDate=issue.publishDate,
        )

    def _absUrl(self, href: str) -> str:
        """将相对 URL 转为绝对 URL。"""
        if href.startswith("http"):
            return href
        # href 形如 "../WebPublication/paperDigest.aspx?paperID=..."
        return urljoin(self.BASE_URL, href)

    def fetchAbstracts(self, articles: List[Article]) -> List[Article]:
        """尝试获取摘要。CNKI 详情页需验证码，通常失败，留空降级。"""
        # 实测详情页有验证码保护，无法自动获取。
        # 保留接口以便未来支持（如手动提供cookie或换数据源）。
        for art in articles:
            if art.abstract:
                continue
            art.abstract = ""  # 明确留空
            log.debug(
                "摘要未获取（CNKI详情页需验证码）: %s", art.title[:30]
            )
        return articles
