"""Zotero 客户端集成 — 基于 pyzotero (Web API v3)。

功能：
- 按名称逐级定位 Collection（不自动创建用户目录）
- 创建期刊文章条目（含完整 metadata）
- 挂载 PDF 附件
- 添加标签
- 查重（标题匹配）
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .models import Article
from .title_matcher import normalizeTitle

log = logging.getLogger(__name__)


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

    def checkDuplicate(self, article: Article) -> Optional[str]:
        """按标题检索 Zotero，返回已存在条目的 key（无则 None）。

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
                if normalizeTitle(data.get("title", "")) == target:
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
            successful = resp.get("successful") or resp.get("success") or {}
            if isinstance(successful, dict):
                created = successful.get("0")
                if isinstance(created, dict) and created.get("key"):
                    return created["key"]
                if isinstance(created, str):
                    return created
            if resp.get("failed"):
                log.error("创建条目失败: %s", resp.get("failed"))
            return None
        except Exception as e:
            log.error("创建条目异常: %s", e)
            return None

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
        """挂载 PDF 附件到指定条目。"""
        if not os.path.exists(pdfPath):
            log.error("PDF 文件不存在: %s", pdfPath)
            return False
        try:
            resp = self.zot.attachment_simple([pdfPath], parentid=itemKey)
            return bool(resp.get("successful") or resp.get("success"))
        except Exception as e:
            log.error("挂载 PDF 异常: %s", e)
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
            return {"status": "skipped", "key": existing, "reason": "标题已存在"}

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

        itemKey = self.createArticleItem(
            article,
            collectionKey,
            extraText=extraText,
            extraTags=extraTags,
        )
        if not itemKey:
            return {"status": "failed", "key": "", "reason": "创建条目失败"}

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
