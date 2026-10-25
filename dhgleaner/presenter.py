"""阶段二：目录呈现。

将捕获的新文章格式化为 Markdown 表格，供研究者判断。
文章使用全局编号（跨期刊递增），便于用户用编号选择。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from .keywords import tagArticles
from .models import STATUS_IMPORTED, STATUS_PRESENTED, STATUS_SELECTED, Article, IssueInfo
from .selection_basket import parseIndexSpec

_TZ = timezone(timedelta(hours=8))




def _issueLabelForArticle(article: Article) -> str:
    return article.issueDisplay or article.issueInfo().label()


def _headingLabel(issue: Optional[IssueInfo], articles: List[Article]) -> str:
    if articles and all((a.sourceType or "issue") == "channel" for a in articles):
        channel = articles[0].section or "栏目"
        return f"{channel}栏目清单"
    if articles and all((a.sourceType or "issue") == "harvest" for a in articles):
        year = articles[0].year
        return f"{year}年散篇清单" if year else "散篇清单"
    if issue:
        return issue.label()
    return ""

def _escapeCell(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def renderCatalog(
    captureResults: List[Tuple[str, Optional[IssueInfo], List[Article]]],
) -> Tuple[str, List[Article]]:
    """将捕获结果渲染为 Markdown 目录。"""
    now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"## 📰 数字人文期刊新刊速递（{now} 捕获）\n"]

    allArticles: List[Article] = []
    for _, _, articles in captureResults:
        allArticles.extend(articles)

    # 框架级 DH 双标签：capture / channel / harvest 三条流程都在此统一打标，
    # 因此 review.md 与 pending.json 里的每篇文章都带 dhMatched / histAiMatched。
    tagArticles(allArticles)

    hasAny = len(allArticles) > 0
    globalIdx = 0

    for name, issue, articles in captureResults:
        if not issue:
            lines.append(f"### 《{name}》\n\n> ⚠️ 抓取失败或未能定位到当期目录\n")
            continue
        if not articles:
            dateStr = f"（{issue.publishDate} 刊出）" if issue.publishDate else ""
            lines.append(f"### 《{name}》{_headingLabel(issue, articles)}{dateStr}\n\n> ⏳ 当前期次无新文章（已处理过）\n")
            continue

        dateStr = f"（{issue.publishDate} 刊出）" if issue.publishDate and issue.year else ""
        lines.append(f"### 《{name}》{_headingLabel(issue, articles)}{dateStr}\n")
        sourceNotes = sorted({a.sourceNote for a in articles if a.sourceNote})
        for note in sourceNotes[:3]:
            lines.append(f"> {_escapeCell(note)}\n")

        sections: dict = {}
        for article in articles:
            article.status = STATUS_PRESENTED
            sections.setdefault(article.section or "未分类", []).append(article)

        for section, arts in sections.items():
            lines.append(f"**{_escapeCell(section)}**\n")
            includeIssue = any((a.sourceType or "issue") == "channel" or a.issueDisplay for a in arts)
            includeHits = all((a.sourceType or "issue") == "harvest" for a in arts) and any(
                a.dhMatched or a.histAiMatched for a in arts
            )
            header = ["#", "标题"]
            if includeIssue:
                header.append("年卷期")
            header += ["作者", "页码", "PDF", "摘要"]
            if includeHits:
                header.append("命中")
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["------"] * len(header)) + "|")
            for article in arts:
                globalIdx += 1
                article._globalIndex = globalIdx
                title = _escapeCell(article.title)
                authors = ", ".join(article.authors[:3])
                if len(article.authors) > 3:
                    authors += " 等"
                authors = _escapeCell(authors)
                pages = _escapeCell(article.pagesStr() or "—")
                pdf = _escapeCell(article.pdfSize or ("有" if article.pdfUrl else "无"))
                absFlag = _escapeCell(f"有({len(article.abstract)}字)") if article.abstract else "无"
                cells = [str(globalIdx), title]
                if includeIssue:
                    cells.append(_escapeCell(_issueLabelForArticle(article)))
                cells += [authors, pages, pdf, absFlag]
                if includeHits:
                    hits = list(article.dhMatched)[:4] or list(article.histAiMatched)[:4]
                    cells.append(_escapeCell(",".join(hits)) or "—")
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")

    if hasAny:
        lines.append("---")
        lines.append("## 摘要筛选")
        lines.append("")
        for article in allArticles:
            idx = getattr(article, "_globalIndex", 0)
            authors = _escapeCell(", ".join(article.authors) or "—")
            lines.append(f"### #{idx} {_escapeCell(article.title)}")
            lines.append(f"- 作者: {authors}")
            lines.append(f"- 期刊: 《{_escapeCell(article.journal)}》 {_escapeCell(_issueLabelForArticle(article))}")
            section = _escapeCell(article.section or "未分类")
            pages = _escapeCell(article.pagesStr() or "—")
            articleUrl = _escapeCell(article.articleUrl or "—")
            lines.append(f"- 栏目: {section}")
            lines.append(f"- 页码: {pages}")
            lines.append(f"- 原文链接: {articleUrl}")
            if article.keywords:
                lines.append(f"- 关键词: {_escapeCell(article.keywords)}")
            if article.dhMatched:
                lines.append(f"- 数字人文命中: {_escapeCell(', '.join(article.dhMatched))}")
            if article.histAiMatched:
                lines.append(f"- 历史学+AI命中: {_escapeCell(', '.join(article.histAiMatched))}")
            if article.sourceNote:
                lines.append(f"- 来源说明: {_escapeCell(article.sourceNote)}")
            if article.pdfUrl:
                pdfLabel = article.pdfSize or "有 PDF 链接"
                lines.append(f"- PDF: {_escapeCell(pdfLabel)}，仅在导入选中文章时处理")
            else:
                lines.append("- PDF: 暂无")
            lines.append("")
            lines.append(article.abstract or "（摘要暂未获取；如需导入，Zotero 条目会保留基本信息并标注摘要需手动补充。）")
            lines.append("")
        lines.append("---")
        lines.append("请根据上方目录和摘要筛选文章，再运行 `dhgleaner import --selection \"编号\"` 只导入需要的文章。")
        lines.append("捕获阶段只保存元数据和摘要，不导入 Zotero，也不下载 PDF。")
    else:
        lines.append("---\n所有期刊均无新文章。")

    return "\n".join(lines), allArticles


def renderAbstract(article: Article) -> str:
    """渲染单篇文章的完整摘要。"""
    lines = [
        f"### {article.title}",
        f"**作者**: {', '.join(article.authors)}",
        f"**期刊**: 《{article.journal}》 {_issueLabelForArticle(article)}",
        f"**页码**: {article.pagesStr() or '—'}",
        f"**链接**: {article.articleUrl}",
        "",
        "**摘要**:",
        article.abstract or "（摘要暂未获取。注：《数字人文》详情页需验证码，摘要需手动补充）",
    ]
    return "\n".join(lines)


def applySelection(
    articles: List[Article], selection: str
) -> List[Article]:
    """根据用户选择标记文章状态。"""
    sel = selection.strip()
    if sel in ("全部", "all", "全选"):
        for article in articles:
            if article.status != STATUS_IMPORTED and not article.zoteroKey:
                article.status = STATUS_SELECTED
        return list(articles)
    if sel in ("都不要", "无", "none", ""):
        for article in articles:
            if article.status != STATUS_IMPORTED and not article.zoteroKey:
                article.status = STATUS_PRESENTED
        return []

    normalized = sel.replace("，", ",").replace("；", ",").replace("、", ",")
    # 与 `screen --add` 共用一个解析器：那边支持 1,3-5、这边不吃区间，同一份编号
    # 写两种语法，使用者按记熟的那条写就会静默选空。
    try:
        nums = set(parseIndexSpec(normalized))
    except ValueError as e:
        raise ValueError(f"选择表达式无法解析：{sel}（{e}；支持 1,3,5 与 3-5）") from None

    selected = []
    for article in articles:
        idx = getattr(article, "_globalIndex", 0)
        if idx in nums:
            if article.status != STATUS_IMPORTED and not article.zoteroKey:
                article.status = STATUS_SELECTED
            selected.append(article)
        else:
            if article.status != STATUS_IMPORTED and not article.zoteroKey:
                article.status = STATUS_PRESENTED
    return selected


def getArticleByIndex(articles: List[Article], idx: int) -> Optional[Article]:
    """按全局编号查找文章。"""
    for article in articles:
        if getattr(article, "_globalIndex", 0) == idx:
            return article
    return None
