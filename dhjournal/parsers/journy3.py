"""Journy3 解析器 — 《数字人文研究》(dhr.ruc.edu.cn)。

HTML 结构要点（已实测）：
- 期次信息: 文本 "2026年 第6卷 第2期  刊出日期：2026-06-28"
- 栏目标记: <div class="wenzhanglanmu"><A name="栏目名"></A>栏目名</DIV>
- 文章块: <DIV id='art{文章ID}' class=noselectrow>
- 标题:    <a class="biaoti" href="...Y2026/V6/I2/{页码}">标题</a>
- 作者:    <dd class="zuozhe">作者</dd>
- 年卷期页: <dd class="kmnjq">2026, 6(2): 3-17.</dd>
- PDF:     <a href="#1" onclick="lsdy1('PDF','{文章ID}',...)">PDF</a> (9721KB)
- 摘要:    <div id="Abstract{文章ID}" class="white_content zhaiyao">摘要文本</div>
- PDF 真实链接: /CN/article/downloadArticleFile.do?attachType=PDF&id={文章ID}
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


class Journy3Parser(BaseParser):
    """《数字人文研究》解析器 — Journy3（玛格泰克）期刊系统。"""

    BASE_URL = "http://dhr.ruc.edu.cn"

    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        soup = BeautifulSoup(html, "lxml")

        issue = self._parseIssueInfo(soup)
        articles = self._parseArticles(soup, issue)

        log.info(
            "《数字人文研究》解析完成: %s, 共 %d 篇文章",
            issue.label(),
            len(articles),
        )
        return issue, articles

    def _parseIssueInfo(self, soup: BeautifulSoup) -> IssueInfo:
        """从页面文本提取期次信息。"""
        text = soup.get_text(" ", strip=True)
        # 匹配 "2026年 第6卷 第2期 ... 刊出日期：2026-06-28"
        m = re.search(
            r"(\d{4})年\s*第(\d+)卷\s*第(\d+)期.*?刊出日期[：:]\s*([\d-]+)",
            text,
        )
        if m:
            return IssueInfo(
                year=int(m.group(1)),
                volume=int(m.group(2)),
                issue=int(m.group(3)),
                publishDate=m.group(4),
            )
        # 降级：仅年卷期，无刊出日期
        m = re.search(r"(\d{4})年\s*第(\d+)卷\s*第(\d+)期", text)
        if m:
            return IssueInfo(
                year=int(m.group(1)),
                volume=int(m.group(2)),
                issue=int(m.group(3)),
            )
        log.warning("未能从页面提取期次信息，使用默认值")
        return IssueInfo(year=0, volume=0, issue=0)

    def _parseArticles(
        self, soup: BeautifulSoup, issue: IssueInfo
    ) -> List[Article]:
        """解析文章列表，跟踪当前栏目。"""
        articles: List[Article] = []
        currentSection = ""

        # 栏目标记: <div class="wenzhanglanmu"><A name="栏目名"></A>栏目名</DIV>
        # 文章块: <div id='art{id}' class=noselectrow>
        # 按 DOM 顺序遍历，遇到栏目标记更新 currentSection，遇到文章块解析
        for el in soup.find_all(
            ["div"], class_=re.compile(r"wenzhanglanmu|noselectrow")
        ):
            cls = " ".join(el.get("class", []))
            if "wenzhanglanmu" in cls:
                # 栏目名：取 <A name="..."> 的 name 属性，或文本
                a = el.find("a", attrs={"name": True})
                if a:
                    currentSection = a.get("name", "").strip()
                else:
                    currentSection = el.get_text(strip=True)
                log.debug("进入栏目: %s", currentSection)
            elif "noselectrow" in cls:
                art = self._parseOneArticle(el, issue, currentSection)
                if art:
                    articles.append(art)

        return articles

    def _parseOneArticle(
        self, block, issue: IssueInfo, section: str
    ) -> Optional[Article]:
        """解析单篇文章块；缺少标题/链接时返回 None。"""
        # 文章ID（用于构造 PDF 链接）
        blockId = block.get("id", "")  # art172
        articleId = blockId.replace("art", "") if blockId.startswith("art") else ""

        # 标题与链接
        titleA = block.find("a", class_="biaoti")
        if not titleA:
            log.warning("文章块缺少标题: %s", blockId)
            return None
        title = titleA.get_text(strip=True)
        articleUrl = urljoin(self.BASE_URL, titleA.get("href", ""))

        # 作者
        authorDd = block.find("dd", class_="zuozhe")
        authors = []
        if authorDd:
            authorText = authorDd.get_text(strip=True)
            # 多作者按逗号/顿号/分号分隔
            authors = [
                a.strip()
                for a in re.split(r"[,，;；]", authorText)
                if a.strip()
            ]

        # 年卷期页: <dd class="kmnjq">2026, 6(2): 3-17.</dd>
        kmnjqDd = block.find("dd", class_="kmnjq")
        startPage, endPage = 0, 0
        if kmnjqDd:
            pageText = kmnjqDd.get_text(" ", strip=True)
            pm = re.search(r"(\d+)-(\d+)", pageText)
            if pm:
                startPage, endPage = int(pm.group(1)), int(pm.group(2))

        # PDF: onclick="lsdy1('PDF','172',...)" + "(9721KB)"
        pdfUrl = ""
        pdfSize = ""
        pdfA = None
        for a in block.find_all("a"):
            onclick = a.get("onclick", "")
            if "lsdy1" in onclick and "PDF" in onclick:
                pdfA = a
                break
        if pdfA:
            # 提取文章ID
            om = re.search(r"lsdy1\('PDF','(\d+)'", pdfA.get("onclick", ""))
            if om:
                articleId = om.group(1)
            # PDF大小: 后面的 (9721KB) 文本
            pdfSize = self._extractPdfSize(pdfA)

        if articleId:
            pdfUrl = urljoin(
                self.BASE_URL,
                f"/CN/article/downloadArticleFile.do?attachType=PDF&id={articleId}",
            )

        # 摘要: <div id="Abstract{id}" class="white_content zhaiyao">
        abstract = ""
        if articleId:
            absDiv = block.find(id=f"Abstract{articleId}")
            if absDiv:
                abstract = absDiv.get_text(strip=True)

        return Article(
            journal=self.journalName,
            year=issue.year,
            volume=issue.volume,
            issue=issue.issue,
            section=section,
            title=title,
            authors=authors,
            abstract=abstract,
            startPage=startPage,
            endPage=endPage,
            articleUrl=articleUrl,
            pdfUrl=pdfUrl,
            pdfSize=pdfSize,
            publishDate=issue.publishDate,
        )

    def _extractPdfSize(self, pdfA) -> str:
        """从 PDF 链接后的文本提取文件大小，如 '9721KB'。"""
        # PDF (9721KB) — 大小在 <a> 的下一个兄弟文本节点
        parent = pdfA.parent
        if parent:
            text = parent.get_text(" ", strip=True)
            sm = re.search(r"(\d+\s*KB)", text, re.I)
            if sm:
                return sm.group(1).replace(" ", "")
        return ""
