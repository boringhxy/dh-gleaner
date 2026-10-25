"""Zotero 客户端集成 — 基于 pyzotero (Web API v3)。

功能：
- 按名称逐级定位 Collection（不自动创建用户目录）
- 创建期刊文章条目（含完整 metadata）
- 挂载 PDF 附件
- 添加标签
- 查重（题名候选 + DOI/URL/书目身份核验）
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

from .models import Article
from .title_matcher import normalizeTitle

log = logging.getLogger(__name__)

# 「请求可能已经写进去了，只是响应没回来」的那类错误特征。Zotero 服务端提交写入
# 之后连接才断（实测 `Server disconnected without sending a response.`）时，条目其实
# 已经在库里；把它报成「创建条目失败」，使用者重跑就会看到一条自相矛盾的「跳过」。
_CONNECTION_MARKERS = (
    "disconnected", "connection reset", "connection aborted", "connection refused",
    "timed out", "timeout", "chunkedencoding", "remoteprotocol", "readerror",
    "connecterror", "networkerror", "eof occurred",
)
# 凭据/userID 被拒：重试一万次也不会好，必须和「网络抖了一下」分开说。
_REJECTED_MARKERS = (
    "401", "403", "412", "invalid user id", "unauthorized", "forbidden",
    "incorrect library id", "key is not valid",
)


def classifyCreationFailure(error: Exception) -> tuple[str, bool]:
    """把创建条目时抛出的异常归成 (kind, committed)。

    kind 取 `connection` / `rejected` / `api`；committed 表示写入可能已在服务端完成，
    需要回查而不是直接判失败。按异常类名与报文判断而不 isinstance(httpx.*)：httpx 只是
    pyzotero 的传递依赖，把它写成本模块的直接依赖会让「换一个 HTTP 后端」变成改代码。
    """
    signal = f"{type(error).__name__} {error}".lower()
    if any(marker in signal for marker in _REJECTED_MARKERS):
        return "rejected", False
    if any(marker in signal for marker in _CONNECTION_MARKERS):
        return "connection", True
    return "api", False


class ItemCreationError(Exception):
    """创建条目失败，携带可给使用者看的分类信息。"""

    def __init__(self, kind: str, detail: str, committed: bool = False):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.committed = committed


class ZoteroClient:
    """Zotero 操作封装。"""

    # 查重时最多扫描多少条命中结果：足够覆盖正常命中量，又能防止标题过短
    # 命中海量条目时把整个库翻下来。
    DUPLICATE_SCAN_LIMIT = 300

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mode = cfg.get("mode", "web")
        self.libraryId = cfg.get("webLibraryId", "")
        self.apiKey = cfg.get("webApiKey", "")
        self.libraryType = cfg.get("libraryType", "user")
        self.collectionPath = cfg.get("collectionPath", [])
        self.journalCollections = cfg.get("journalCollections", {})
        self.autoCreate = cfg.get("autoCreateCollection", False)
        self._zot = None
        self._collectionCache: dict = {}
        # 本次运行内自动新建的 Collection 名称，按层级从上到下；用于向用户交代写了什么
        self.createdCollections: list[str] = []
        # 读取 Collection 列表时的 API 错误；非空时「找不到目录」这个结论不可信
        self.collectionReadError: Optional[str] = None

    @property
    def zot(self):
        """惰性初始化 pyzotero 客户端。"""
        if self._zot is None:
            if not self.libraryId or not self.apiKey:
                from .config import credentialHint

                raise RuntimeError(
                    "未配置你自己的 Zotero 凭据（zotero.webLibraryId / zotero.webApiKey）。\n"
                    + credentialHint()
                )
            from pyzotero.zotero import Zotero

            self._zot = Zotero(
                self.libraryId,
                self.libraryType,
                self.apiKey,
            )
        return self._zot

    def testConnection(self) -> bool:
        """测试连接是否正常。"""
        try:
            self.zot.key_info()
            return True
        except Exception as e:
            log.error("Zotero 连接失败: %s", e)
            return False

    def _allCollections(self) -> list:
        """获取全量 Collection，避免默认 limit=100 导致深层目录漏查。"""
        if "all" not in self._collectionCache:
            self._collectionCache["all"] = self.zot.everything(self.zot.collections())
        return self._collectionCache["all"]

    def _createCollection(self, name: str, parentKey: Optional[str], depth: int) -> Optional[str]:
        """新建一个 Collection 并返回其 key；仅在 autoCreateCollection 为真时被调用。"""
        try:
            result = self.zot.create_collections([{"name": name, "parentCollection": parentKey or False}])
        except Exception as e:
            log.error("创建 Collection 失败: %s (%s)", name, e)
            return None
        successful = (result or {}).get("successful") or {}
        created = successful.get("0") or {}
        key = created.get("key")
        if not key:
            log.error("创建 Collection 未成功: %s (%s)", name, result)
            return None
        log.info("已新建 Collection: %s%s", "  " * depth, name)
        self.createdCollections.append(name)
        self._collectionCache.pop("all", None)  # 目录已变化，缓存作废
        return key

    def _findChild(self, collections: list, name: str, parentKey: Optional[str], depth: int) -> Optional[str]:
        """在指定父层级下按名称查找 Collection，返回 key。"""
        for col in collections:
            colName = col["data"].get("name", "")
            colParent = col["data"].get("parentCollection", False)
            isTopLevel = depth == 0 and (colParent is False or not colParent)
            isChild = depth > 0 and colParent == parentKey
            if colName == name and (isTopLevel or isChild):
                return col["key"]
        return None

    def _collectionPathNames(self, journalName: str) -> list[str]:
        names = list(self.collectionPath) + [self.journalCollections.get(journalName, "")]
        return [name for name in names if name]

    def locateJournalCollection(self, journalName: str, createIfMissing: Optional[bool] = None) -> Optional[str]:
        """定位期刊对应的 Collection key。

        `createIfMissing` 缺省时取 `zotero.autoCreateCollection`（默认关闭，不擅自改动
        用户的 Zotero 库）；显式传 `False` 可强制只读——MCP 的导入预览就走这条路。
        新建的名称记录在 `self.createdCollections`。
        """
        allowCreate = self.autoCreate if createIfMissing is None else bool(createIfMissing)
        try:
            collections = self._allCollections()
        except Exception as e:
            # 返回 None 之外还要留痕：调用方据此区分「目录真的不存在」和「没读成」，
            # 否则 400 Invalid user ID 会被报成「Collection 路径不存在」。
            self.collectionReadError = str(e) or type(e).__name__
            log.error("获取 collections 失败: %s", e)
            return None

        currentKey = None
        for depth, name in enumerate(self._collectionPathNames(journalName)):
            found = self._findChild(collections, name, currentKey, depth)
            if not found:
                if not allowCreate:
                    log.warning("未找到 Collection: %s (路径层级 %d)", name, depth)
                    return None
                found = self._createCollection(name, currentKey, depth)
                if not found:
                    return None
            currentKey = found

        return currentKey

    def collectionPlan(self, journalName: str) -> dict:
        """只读预检：报告该刊 Collection 路径里哪些层级已存在、哪些缺失。

        返回 `{"path": 完整路径, "missing": 首个缺失层级起的所有名称,
        "resolvedKey": 已存在的最深层级 key（全缺失时为 None）, "error": ...}`。

        与 `locateJournalCollection` 的关键区别是**绝不创建任何东西**，
        因此可以安全地用于「导入前让用户看清楚会写到哪」。
        """
        pathNames = self._collectionPathNames(journalName)
        try:
            collections = self._allCollections()
        except Exception as e:
            return {"path": pathNames, "missing": [], "resolvedKey": None, "error": str(e)}

        currentKey = None
        missing: list[str] = []
        for depth, name in enumerate(pathNames):
            found = self._findChild(collections, name, currentKey, depth)
            if not found:
                missing = pathNames[depth:]
                break
            currentKey = found
        return {"path": pathNames, "missing": missing, "resolvedKey": currentKey, "error": None}

    @staticmethod
    def _sameArticle(article: Article, data: dict) -> bool:
        def doi(value):
            return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I).lower()

        incomingDoi, existingDoi = doi(article.doi), doi(data.get("DOI"))
        if incomingDoi and existingDoi:
            return incomingDoi == existingDoi
        if article.articleUrl and data.get("url") == article.articleUrl:
            return True
        if normalizeTitle(data.get("title", "")) != normalizeTitle(article.title):
            return False
        journal = normalizeTitle(data.get("publicationTitle", ""))
        incomingJournal = normalizeTitle(article.journal)
        yearMatch = re.search(r"(?<!\d)(\d{4})(?!\d)", str(data.get("date", "")))
        year = int(yearMatch.group(1)) if yearMatch else 0
        if journal and incomingJournal and journal != incomingJournal:
            return False
        if year and article.year and year != article.year:
            return False
        authors = {
            normalizeTitle(c.get("name") or (c.get("firstName", "") + c.get("lastName", "")))
            for c in data.get("creators", []) if c.get("creatorType", "author") == "author"
        } - {""}
        incomingAuthors = {normalizeTitle(a) for a in article.authors} - {""}
        if authors and incomingAuthors and not authors.intersection(incomingAuthors):
            return False
        return bool(year and year == article.year and (
            (journal and journal == incomingJournal) or authors.intersection(incomingAuthors)
        ))

    def checkDuplicate(self, article: Article) -> Optional[str]:
        """按题名查候选，以 DOI 或书目信息确认身份，返回已存在条目的 key。

        用 `everything()` 翻页而不是只取首页：短标题或常见词可能命中很多条目，
        只取 limit 条会漏判，导致把已入库的文章重复导入。标题用 `normalizeTitle`
        归一化后比较，容忍全半角、引号、破折号与标点差异。
        """
        target = normalizeTitle(article.title)
        if not target:
            return None
        try:
            results = self.zot.everything(self.zot.items(q=article.title, limit=100))
            for scanned, item in enumerate(results, 1):
                if scanned > self.DUPLICATE_SCAN_LIMIT:
                    log.info(
                        "查重扫描已达上限 %d 条仍未精确命中，停止: %s",
                        self.DUPLICATE_SCAN_LIMIT, article.title[:30],
                    )
                    break
                data = item.get("data", {})
                if data.get("itemType") != "journalArticle":
                    continue
                if self._sameArticle(article, data):
                    return item["key"]
        except Exception as e:
            log.warning("查重失败: %s", e)
        return None

    def createArticleItem(
        self,
        article: Article,
        collectionKey: Optional[str] = None,
        extraText: str = "",
        extraTags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """创建期刊文章条目。"""
        template = self.zot.item_template("journalArticle")
        template["title"] = article.title
        template["publicationTitle"] = article.journal
        template["volume"] = str(article.volume) if article.volume else ""
        template["issue"] = str(article.issue) if article.issue else ""
        template["date"] = article.publishDate or str(article.year)
        template["pages"] = article.pagesStr()
        template["abstractNote"] = article.abstract or ""
        template["DOI"] = article.doi or ""
        template["url"] = article.articleUrl
        template["libraryCatalog"] = "数字人文期刊官网"
        template["rights"] = "开放获取" if article.journal == "数字人文研究" else ""
        template["creators"] = [
            {"creatorType": "author", "firstName": "", "lastName": name}
            for name in article.authors
        ]
        if collectionKey:
            template["collections"] = [collectionKey]
        tags = self._buildTags(article)
        if extraTags:
            tags.extend(extraTags)
        template["tags"] = [{"tag": tag} for tag in tags]
        if extraText:
            template["extra"] = extraText

        try:
            resp = self.zot.create_items([template])
        except Exception as e:
            kind, committed = classifyCreationFailure(e)
            log.error("创建条目异常(%s): %s", kind, e)
            raise ItemCreationError(kind, str(e) or type(e).__name__, committed=committed) from e
        successful = resp.get("successful") or resp.get("success") or {}
        if isinstance(successful, dict):
            created = successful.get("0")
            if isinstance(created, dict) and created.get("key"):
                return created["key"]
            if isinstance(created, str):
                return created
        detail = str(resp.get("failed") or resp)
        log.error("创建条目失败: %s", detail)
        raise ItemCreationError("api", detail)

    def _buildTags(self, article: Article) -> List[str]:
        """构建标签列表。"""
        tags = [
            f"期刊:{article.journal}",
            article.issueInfo().issueTag(),
            f"年份:{article.year}",
        ]
        if article.section:
            tags.append(f"栏目:{article.section}")
        return tags

    def attachPdf(
        self, itemKey: str, pdfPath: str, title: str = "全文PDF"
    ) -> bool:
        """挂载 PDF 附件到指定条目。

        不用 `attachment_simple`：它先创建附件记录再上传文件，配额满等上传失败
        会抛异常且新记录的 key 被吞掉，库里留下「记录在、文件哪都不在」的悬空
        附件（桌面端打开报「找不到文件」）。拆成创建 + 上传两步，失败时删除刚
        创建的记录。
        """
        if not os.path.exists(pdfPath):
            log.error("PDF 文件不存在: %s", pdfPath)
            return False
        created = None
        try:
            template = self.zot.item_template("attachment")
            template.update({
                "title": os.path.basename(pdfPath),
                "parentItem": itemKey,
                "linkMode": "imported_file",
                "contentType": "application/pdf",
                "charset": "",
                # 服务端拒绝 filename 含目录路径，创建时只能给 basename
                "filename": os.path.basename(pdfPath),
            })
            resp = self.zot.create_items([template])
            created = (resp.get("successful") or resp.get("success") or {}).get("0") or {}
            key = created.get("key")
            if not key:
                log.error("创建附件记录失败: %s", resp.get("failed") or resp)
                return False
            result = self.zot.upload_attachments(
                [{**template, "key": key, "filename": pdfPath}]
            )
            if result.get("success") or result.get("unchanged"):
                return True
            log.error("上传 PDF 未成功: %s", result.get("failure"))
        except Exception as e:
            log.error("挂载 PDF 异常: %s", e)
        if created and created.get("key"):
            try:
                self.zot.delete_item({"key": created["key"], "version": created.get("version", 0)})
                log.info("已回滚悬空附件记录: %s", created["key"])
            except Exception as e:
                log.error("回滚附件记录 %s 失败，需手动删除: %s", created["key"], e)
        return False


    def attachUrl(
        self, itemKey: str, url: str, title: str = "PDF下载链接"
    ) -> bool:
        """以 linked_url 附件形式记录下载链接。"""
        if not url:
            return False
        try:
            template = self.zot.item_template("attachment", linkmode="linked_url")
            template["title"] = title
            template["url"] = url
            template["parentItem"] = itemKey
            resp = self.zot.create_items([template])
            return bool(resp.get("successful") or resp.get("success"))
        except Exception as e:
            log.error("记录 PDF 链接附件异常: %s", e)
            return False

    def _describeCreationFailure(self, article: Article, error: ItemCreationError) -> dict:
        """把创建失败翻译成人能据此决定下一步的话，而不是一律「创建条目失败」。"""
        if error.committed:
            # 写入可能已经提交、只是响应丢了：回查一次，别让人以为没写进去而重复导。
            existing = self.checkDuplicate(article)
            if existing:
                log.info("创建响应中断但条目已存在: %s (%s)", article.title[:30], existing)
                return {
                    "status": "skipped",
                    "key": existing,
                    "reason": "写入已完成，只是响应中断；条目已存在于库中，无需重跑",
                }
            return {
                "status": "failed",
                "key": "",
                "reason": f"与 Zotero 的连接中断，未能确认是否写入；重跑一次（若报「同一文献已存在」说明其实写成了）：{error.detail[:120]}",
            }
        if error.kind == "rejected":
            return {
                "status": "failed",
                "key": "",
                "reason": f"Zotero 拒绝写入，重试无用（检查 webLibraryId 是否为数字 userID、webApiKey 是否有效）：{error.detail[:120]}",
            }
        return {"status": "failed", "key": "", "reason": f"创建条目失败：{error.detail[:160]}"}

    def importArticle(
        self,
        article: Article,
        pdfPath: Optional[str] = None,
        collectionKey: Optional[str] = None,
        pdfUrlForNote: str = "",
    ) -> dict:
        """完整导入一篇文章：查重 → 创建条目 → 挂载PDF。"""
        existing = self.checkDuplicate(article)
        if existing:
            log.info("跳过（已存在）: %s", article.title[:40])
            return {"status": "skipped", "key": existing, "reason": "同一文献已存在"}

        extraParts = []
        extraTags = []
        if article.issueDisplay:
            extraParts.append(f"原站年卷期: {article.issueDisplay}")
        if article.sourceType and article.sourceType != "issue":
            extraParts.append(f"来源类型: {article.sourceType}")
        if article.sourceNote:
            extraParts.append(f"来源说明: {article.sourceNote}")
        if not article.abstract:
            extraParts.append("摘要需手动补充")
        if pdfUrlForNote:
            if article.failReason:
                extraParts.append(f"PDF自动获取失败: {article.failReason}")
            extraParts.append(f"PDF下载链接: {pdfUrlForNote}")
            extraParts.append("（需登录学校/CNKI账号或手动访问期刊页面后下载）")
            extraTags.append("PDF待手动下载")
        extraText = " | ".join(extraParts)

        try:
            itemKey = self.createArticleItem(
                article,
                collectionKey,
                extraText=extraText,
                extraTags=extraTags,
            )
        except ItemCreationError as e:
            return self._describeCreationFailure(article, e)
        if not itemKey:
            return {"status": "failed", "key": "", "reason": "创建条目失败：服务端未返回新条目的 key"}

        pdfOk = False
        linkRecorded = False
        if pdfPath:
            pdfOk = self.attachPdf(itemKey, pdfPath)
            if not pdfOk and article.pdfUrl:
                linkRecorded = self.attachUrl(itemKey, article.pdfUrl, title="PDF下载链接（未挂载）")
        elif pdfUrlForNote:
            linkRecorded = self.attachUrl(itemKey, pdfUrlForNote, title="PDF下载链接（需手动下载）")

        if pdfOk:
            reason = "PDF已挂载"
        elif linkRecorded:
            reason = "条目已创建，PDF未挂载，已记录下载链接"
        elif pdfUrlForNote or article.pdfUrl:
            reason = "条目已创建，PDF需手动下载"
        else:
            reason = "条目已创建，PDF未挂载"
        return {
            "status": "imported",
            "key": itemKey,
            "pdfAttached": pdfOk,
            "pdfLinkRecorded": linkRecorded,
            "reason": reason,
        }
