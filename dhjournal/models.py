"""标准数据模型 — 两个期刊的解析器统一输出 Article 对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# 状态机: new → presented → selected → imported / failed
STATUS_NEW = "new"
STATUS_PRESENTED = "presented"
STATUS_SELECTED = "selected"
STATUS_IMPORTED = "imported"
STATUS_FAILED = "failed"


@dataclass
class IssueInfo:
    """期次信息"""
    year: int
    volume: Optional[int] = None   # 《数字人文研究》有卷号；《数字人文》无
    issue: int = 0
    publishDate: str = ""          # 刊出日期，如 "2026-06-28"

    def key(self) -> str:
        """期次唯一标识，用于幂等比对"""
        if self.volume:
            return f"Y{self.year}/V{self.volume}/I{self.issue}"
        return f"Y{self.year}/I{self.issue}"

    def label(self) -> str:
        """可读标签，如 '2026年 第6卷 第2期' 或 '2025年第4期'"""
        if self.volume:
            return f"{self.year}年 第{self.volume}卷 第{self.issue}期"
        return f"{self.year}年第{self.issue}期"

    def issueTag(self) -> str:
        """期次定位标签，如 '2026-Vol6-No2' 或 '2025-No4'"""
        if self.volume:
            return f"{self.year}-Vol{self.volume}-No{self.issue}"
        return f"{self.year}-No{self.issue}"


@dataclass
class Article:
    """标准化文章对象 — 两个期刊解析器的统一输出"""
    journal: str                   # "数字人文研究" | "数字人文"
    year: int
    volume: Optional[int]
    issue: int
    section: str = ""              # 栏目
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    startPage: int = 0
    endPage: int = 0
    doi: str = ""
    issueDisplay: str = ""         # 原站点显示的期次字符串，如 "2025, 44(416)"
    totalIssue: Optional[int] = None # 总期号或站点内部期号，无法确认年度期号时保留
    sourceType: str = "issue"       # issue/channel/manual_curated
    sourceNote: str = ""            # 来源说明或降级原因
    articleUrl: str = ""
    pdfUrl: str = ""
    pdfSize: str = ""              # 如 "9721KB"
    publishDate: str = ""
    capturedAt: str = ""
    status: str = STATUS_NEW
    zoteroKey: str = ""            # 导入后记录的 Zotero item key
    failReason: str = ""           # 失败原因

    def articleKey(self) -> str:
        """文章唯一标识，用于 state.json 幂等去重"""
        if self.articleUrl:
            # 从 URL 提取标识部分
            return self.articleUrl
        return f"{self.journal}|{self.year}|{self.issue}|{self.title}"

    def issueInfo(self) -> IssueInfo:
        return IssueInfo(
            year=self.year,
            volume=self.volume,
            issue=self.issue,
            publishDate=self.publishDate,
        )

    def issueLabel(self) -> str:
        if self.issueDisplay:
            return self.issueDisplay
        return self.issueInfo().label()

    def pagesStr(self) -> str:
        if self.startPage and self.endPage:
            return f"{self.startPage}-{self.endPage}"
        if self.startPage:
            return str(self.startPage)
        return ""

    def toDict(self) -> dict:
        return asdict(self)

    @classmethod
    def fromDict(cls, d: dict) -> "Article":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
