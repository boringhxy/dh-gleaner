"""解析器基类 — 定义统一接口。"""

from __future__ import annotations

import abc
from typing import List, Tuple

from ..models import Article, IssueInfo


class BaseParser(abc.ABC):
    """期刊解析器抽象基类。两个期刊各实现一个子类，统一输出 Article。"""

    def __init__(self, journalName: str, httpCfg: dict):
        self.journalName = journalName
        self.userAgent = httpCfg.get("userAgent", "")
        self.timeout = httpCfg.get("timeout", 30)
        self.maxRetries = httpCfg.get("maxRetries", 3)
        self.retryInterval = httpCfg.get("retryInterval", 30)

    @abc.abstractmethod
    def parseCurrentIssue(self, html: str) -> Tuple[IssueInfo, List[Article]]:
        """解析当期目录页 HTML，返回 (期次信息, 文章列表)。

        文章列表中的每篇 Article 已填入：
        journal/year/volume/issue/section/title/authors/pages/pdfUrl/pdfSize/abstract 等字段。
        abstract 可为空（若需额外请求详情页，在 fetchAbstracts 中补全）。
        """
        ...

    def fetchAbstracts(self, articles: List[Article]) -> List[Article]:
        """补全摘要（若当期页未直接展示）。默认无操作。"""
        return articles
