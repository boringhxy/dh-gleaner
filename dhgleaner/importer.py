"""阶段三：Zotero 导入与归档。

对用户确认的文章：下载PDF → 创建Zotero条目 → 挂载PDF → 归入Collection → 打标签。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .http_util import downloadFile
from .models import STATUS_FAILED, STATUS_IMPORTED, Article
from .state import StateManager
from .zotero_client import ZoteroClient

log = logging.getLogger(__name__)
_TZ = timezone(timedelta(hours=8))


@dataclass
class ImportSummary:
    """一次导入的结构化结果。

    存在的理由：调用方（尤其是 MCP 工具）必须能区分「真的写进去了几篇」
    与「预检就中止了、一篇都没写」。只看 Markdown 报告的数字会误报成功。
    """

    report: str
    attempted: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    aborted: bool = False
    abortReason: str = ""
    createdCollections: List[str] = field(default_factory=list)

    @property
    def wroteAnything(self) -> bool:
        return self.imported + self.skipped > 0



def _isPdf(path: str) -> bool:
    """检查文件头是否为 PDF（%PDF-）。"""
    try:
        with open(path, "rb") as f:
            header = f.read(5)
        return header == b"%PDF-"
    except Exception:
        return False


def _escapeCell(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _markCompleteIssues(
    articles: List[Article],
    state: StateManager,
):
    seen = set()
    for article in articles:
        issue = article.issueInfo()
        issueKey = (article.journal, issue.key())
        if issueKey in seen:
            continue
        seen.add(issueKey)

        issueArticles = [
            a for a in articles
            if a.journal == article.journal and a.issueInfo().key() == issue.key()
        ]
        if issueArticles and all(state.isArticleProcessed(a.journal, a.articleKey()) for a in issueArticles):
            state.markIssueProcessed(article.journal, issue)


def importArticlesDetailed(
    articles: List[Article],
    zotero: ZoteroClient,
    state: StateManager,
    userAgent: str,
    tempDir: str,
    journalConfigs: Optional[dict] = None,
    allPendingArticles: Optional[List[Article]] = None,
) -> ImportSummary:
    """导入已确认的文章到 Zotero，返回结构化结果 + Markdown 报告。"""
    journalConfigs = journalConfigs or {}
    os.makedirs(tempDir, exist_ok=True)
    now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")

    lines = [f"# Zotero 导入报告 — {now}\n"]

    if not articles:
        lines.append("## 提示\n")
        lines.append("没有可导入的文章。")
        return ImportSummary(report="\n".join(lines), aborted=True, abortReason="没有可导入的文章")

    if not zotero.testConnection():
        lines.append("## ⚠️ Zotero 连接失败\n")
        lines.append("请确认网络可用，且你自己的 Zotero 凭据已配置到 config.local.json（webLibraryId / webApiKey）。")
        lines.append("下一步：运行 `dhgleaner init` 交互式录入凭据并测试连接；或 `dhgleaner doctor --zotero` 查看期望路径与密钥模板路径。")
        return ImportSummary(
            report="\n".join(lines), attempted=len(articles),
            aborted=True, abortReason="Zotero 连接失败，未写入任何条目",
        )

    collectionKeys: dict = {}
    missingCollections: List[str] = []
    for article in articles:
        if article.journal in collectionKeys:
            continue
        ck = zotero.locateJournalCollection(article.journal)
        collectionKeys[article.journal] = ck
        if not ck and article.journal not in missingCollections:
            missingCollections.append(article.journal)
            log.warning("未找到《%s》的 Collection 路径", article.journal)

    if missingCollections:
        lines.append("## ⚠️ Collection 路径不存在\n")
        lines.append("以下期刊的 Zotero Collection 路径未找到，已暂停导入：")
        for journalName in missingCollections:
            lines.append(f"- 《{journalName}》")
        lines.append("")
        lines.append("下一步（二选一）：")
        lines.append("1. 运行 `dhgleaner init-collections` 预览缺失目录，确认无误后加 `--yes` 自动补齐；")
        lines.append("2. 或手动在 Zotero 里建好上述目录，再重新运行本次导入。")
        lines.append("（若希望导入时自动补目录，可把配置 zotero.autoCreateCollection 设为 true。）")
        return ImportSummary(
            report="\n".join(lines), attempted=len(articles),
            aborted=True, abortReason=f"未找到 Collection 路径：{'、'.join(missingCollections)}",
            createdCollections=list(getattr(zotero, "createdCollections", []) or []),
        )

    lines.append("## 导入前检查")
    lines.append("- Zotero 连接：通过")
    lines.append("- 目标 Collection：已定位")
    if getattr(zotero, "createdCollections", None):
        lines.append(f"- 本次自动新建目录：{' / '.join(zotero.createdCollections)}")
    lines.append("")

    total = len(articles)
    success = 0
    skipped = 0
    failed = 0
    details = []

    for i, article in enumerate(articles, 1):
        log.info("[%d/%d] 导入: %s", i, total, article.title[:40])

        journalCfg = journalConfigs.get(article.journal, {})
        autoDownloadPdf = journalCfg.get("autoDownloadPdf", True)
        pdfPath = None
        pdfUrlForNote = ""

        pdfHandling = "无 PDF 链接"
        if not autoDownloadPdf:
            if article.pdfUrl:
                pdfUrlForNote = article.pdfUrl
                pdfHandling = "有 PDF 链接，按期刊策略不自动下载，已记录链接"
                log.info("跳过PDF下载（降级策略）: %s", article.title[:30])
            else:
                pdfHandling = "无 PDF 链接"
        elif article.pdfUrl:
            pdfHandling = "有 PDF 链接，尝试自动下载并挂载"
            safeName = f"{article.journal}_{article.year}_{article.issue}_{article.startPage or 'np'}.pdf"
            pdfPath = os.path.join(tempDir, safeName)
            try:
                downloadFile(
                    article.pdfUrl,
                    pdfPath,
                    userAgent,
                    timeout=60,
                    maxRetries=2,
                    retryInterval=10,
                )
                if not _isPdf(pdfPath):
                    log.warning("下载内容非 PDF（可能为验证码页面）: %s", article.title[:30])
                    os.remove(pdfPath)
                    pdfPath = None
                    pdfUrlForNote = article.pdfUrl
                    article.failReason = "PDF下载被拦截(验证码)，链接已记录"
                    pdfHandling = "PDF 下载被拦截，已降级记录链接"
                elif os.path.getsize(pdfPath) < 1024:
                    log.warning("PDF 文件过小，可能无效: %s", pdfPath)
                    os.remove(pdfPath)
                    pdfPath = None
                    pdfUrlForNote = article.pdfUrl
                    article.failReason = "PDF文件过小，已降级为记录链接"
                    pdfHandling = "PDF 文件过小，已降级记录链接"
            except Exception as e:
                log.warning("PDF 下载失败: %s — %s", article.title[:30], e)
                pdfPath = None
                pdfUrlForNote = article.pdfUrl
                article.failReason = f"PDF下载失败，已降级为记录链接: {e}"
                pdfHandling = "PDF 下载失败，已降级记录链接"

        collectionKey = collectionKeys.get(article.journal)
        if not collectionKey:
            article.status = STATUS_FAILED
            article.failReason = "未找到 Collection 路径"
            details.append((article, "failed", "", "Collection路径不存在", pdfHandling))
            failed += 1
            continue

        result = zotero.importArticle(article, pdfPath, collectionKey, pdfUrlForNote=pdfUrlForNote)
        status = result.get("status", "failed")
        zotKey = result.get("key", "")
        reason = result.get("reason", "")

        if status == "imported":
            article.status = STATUS_IMPORTED
            article.zoteroKey = zotKey
            state.markArticleProcessed(article.journal, article.articleKey(), zotKey, article.title, status="imported")
            success += 1
            if result.get("pdfAttached"):
                pdfHandling = "PDF 已挂载"
            elif result.get("pdfLinkRecorded"):
                if not autoDownloadPdf and article.pdfUrl:
                    pdfHandling = "有 PDF 链接，按期刊策略不自动下载，已记录链接"
                else:
                    pdfHandling = "PDF 未挂载，已记录下载链接"
            elif not article.pdfUrl:
                pdfHandling = "无 PDF 链接"
            details.append((article, "imported", zotKey, reason, pdfHandling))
        elif status == "skipped":
            article.status = STATUS_IMPORTED
            article.zoteroKey = zotKey
            state.markArticleProcessed(article.journal, article.articleKey(), zotKey, article.title, status="skipped")
            skipped += 1
            details.append((article, "skipped", zotKey, reason, pdfHandling))
        else:
            article.status = STATUS_FAILED
            article.failReason = reason
            failed += 1
            details.append((article, "failed", "", reason, pdfHandling))

        if pdfPath and os.path.exists(pdfPath):
            try:
                os.remove(pdfPath)
            except OSError:
                pass

    _markCompleteIssues(allPendingArticles or articles, state)

    lines.append("## 导入汇总")
    lines.append(f"- 待导入: {total} 篇")
    lines.append(f"- 成功: {success} 篇")
    lines.append(f"- 跳过（已存在）: {skipped} 篇")
    lines.append(f"- 失败: {failed} 篇\n")

    lines.append("## 明细")
    lines.append("| # | 期刊 | 标题 | 状态 | Zotero Key | PDF处理 | 说明 |")
    lines.append("|---|------|------|------|-----------|---------|------|")
    for i, (article, status, key, reason, pdfHandling) in enumerate(details, 1):
        icon = {"imported": "✅", "skipped": "⏭️", "failed": "❌"}.get(status, "?")
        statusText = {"imported": "成功", "skipped": "跳过", "failed": "失败"}.get(status, status)
        titleShort = article.title[:35] + ("…" if len(article.title) > 35 else "")
        lines.append(
            f"| {i} | {_escapeCell(article.journal)} | {_escapeCell(titleShort)} | "
            f"{icon} {statusText} | {_escapeCell(key or '—')} | {_escapeCell(pdfHandling)} | {_escapeCell(reason)} |"
        )

    return ImportSummary(
        report="\n".join(lines),
        attempted=total,
        imported=success,
        skipped=skipped,
        failed=failed,
        createdCollections=list(getattr(zotero, "createdCollections", []) or []),
    )


def importArticles(
    articles: List[Article],
    zotero: ZoteroClient,
    state: StateManager,
    userAgent: str,
    tempDir: str,
    journalConfigs: Optional[dict] = None,
    allPendingArticles: Optional[List[Article]] = None,
) -> str:
    """兼容入口：只要 Markdown 报告的调用方继续用它。"""
    return importArticlesDetailed(
        articles,
        zotero,
        state,
        userAgent=userAgent,
        tempDir=tempDir,
        journalConfigs=journalConfigs,
        allPendingArticles=allPendingArticles,
    ).report
