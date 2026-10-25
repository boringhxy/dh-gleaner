"""Zotero 客户端用例 —— 重点是 autoCreateCollection 开关的真实行为。"""

from __future__ import annotations

import unittest

from dhgleaner.models import Article
from dhgleaner.zotero_client import ZoteroClient, classifyCreationFailure


class FakeZot:
    """只实现 Collection 相关调用的假客户端。"""

    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.created: list[tuple[str, object]] = []

    def collections(self):
        return iter([])

    def items(self, **_kwargs):
        # 真实客户端会按 q/limit 返回首页；这里 everything() 会忽略它并直接
        # 返回 self.existing，因此只需保证可调用、返回一个可迭代对象。
        return iter([])

    def everything(self, _iterator):
        return list(self.existing)

    def create_collections(self, payload):
        successful = {}
        for index, item in enumerate(payload):
            key = f"NEW{len(self.created)}"
            successful[str(index)] = {"key": key}
            self.created.append((item.get("name"), item.get("parentCollection")))
        return {"successful": successful, "failed": {}}


def buildClient(autoCreate: bool):
    cfg = {
        "webLibraryId": "1",
        "webApiKey": "key",
        "collectionPath": ["10-研究相关", "数字人文"],
        "journalCollections": {"图书馆论坛": "《图书馆论坛》"},
        "autoCreateCollection": autoCreate,
    }
    client = ZoteroClient(cfg)
    fake = FakeZot()
    client._zot = fake
    return client, fake


class LocateCollectionTests(unittest.TestCase):
    def testMissingCollectionReturnsNoneWhenAutoCreateOff(self):
        client, fake = buildClient(False)
        self.assertIsNone(client.locateJournalCollection("图书馆论坛"))
        self.assertEqual(fake.created, [])
        self.assertEqual(client.createdCollections, [])

    def testAutoCreateBuildsFullPathLevelByLevel(self):
        client, fake = buildClient(True)
        collectionKey = client.locateJournalCollection("图书馆论坛")

        self.assertIsNotNone(collectionKey)
        self.assertEqual(
            [name for name, _ in fake.created],
            ["10-研究相关", "数字人文", "《图书馆论坛》"],
        )
        self.assertEqual(
            [parent for _, parent in fake.created],
            [False, "NEW0", "NEW1"],
        )
        self.assertEqual(
            client.createdCollections,
            ["10-研究相关", "数字人文", "《图书馆论坛》"],
        )

    def testExistingPathIsReusedWithoutCreating(self):
        client, fake = buildClient(True)
        fake.existing = [
            {"key": "C1", "data": {"name": "10-研究相关", "parentCollection": False}},
            {"key": "C2", "data": {"name": "数字人文", "parentCollection": "C1"}},
            {"key": "C3", "data": {"name": "《图书馆论坛》", "parentCollection": "C2"}},
        ]
        self.assertEqual(client.locateJournalCollection("图书馆论坛"), "C3")
        self.assertEqual(fake.created, [])
        self.assertEqual(client.createdCollections, [])

    def testPartialPathCreatesOnlyMissingTail(self):
        client, fake = buildClient(True)
        fake.existing = [
            {"key": "C1", "data": {"name": "10-研究相关", "parentCollection": False}},
        ]
        client.locateJournalCollection("图书馆论坛")

        self.assertEqual([name for name, _ in fake.created], ["数字人文", "《图书馆论坛》"])
        self.assertEqual([parent for _, parent in fake.created], ["C1", "NEW0"])

    def testUnconfiguredCredentialsRaiseWithHint(self):
        client = ZoteroClient({"webLibraryId": "", "webApiKey": ""})
        with self.assertRaises(RuntimeError) as ctx:
            _ = client.zot
        self.assertIn("你自己", str(ctx.exception))


class CollectionPlanTests(unittest.TestCase):
    """导入预览依赖的只读预检：绝不能顺手把目录建出来。"""

    def testPlanReportsMissingLevelsWithoutCreating(self):
        client, fake = buildClient(autoCreate=True)
        fake.existing = [
            {"key": "C1", "data": {"name": "10-研究相关", "parentCollection": False}},
        ]
        plan = client.collectionPlan("图书馆论坛")

        self.assertEqual(plan["path"], ["10-研究相关", "数字人文", "《图书馆论坛》"])
        self.assertEqual(plan["missing"], ["数字人文", "《图书馆论坛》"])
        self.assertEqual(plan["resolvedKey"], "C1")  # 已存在的最深层级
        self.assertEqual(fake.created, [])
        self.assertEqual(client.createdCollections, [])

    def testPlanResolvesFullyExistingPath(self):
        client, fake = buildClient(autoCreate=False)
        fake.existing = [
            {"key": "C1", "data": {"name": "10-研究相关", "parentCollection": False}},
            {"key": "C2", "data": {"name": "数字人文", "parentCollection": "C1"}},
            {"key": "C3", "data": {"name": "《图书馆论坛》", "parentCollection": "C2"}},
        ]
        plan = client.collectionPlan("图书馆论坛")

        self.assertEqual(plan["missing"], [])
        self.assertEqual(plan["resolvedKey"], "C3")

    def testLocateWithCreateIfMissingFalseNeverWrites(self):
        """即使全局开着自动建目录，显式传 False 也必须保持只读。"""
        client, fake = buildClient(autoCreate=True)
        self.assertIsNone(client.locateJournalCollection("图书馆论坛", createIfMissing=False))
        self.assertEqual(fake.created, [])

    def testPlanSurfacesErrorWhenCollectionsUnavailable(self):
        client = ZoteroClient({"webLibraryId": "", "webApiKey": "",
                               "collectionPath": ["10-研究相关"], "journalCollections": {}})
        plan = client.collectionPlan("图书馆论坛")
        self.assertIsNotNone(plan["error"])
        self.assertEqual(plan["resolvedKey"], None)


def _item(key: str, title: str, itemType: str = "journalArticle") -> dict:
    return {"key": key, "data": {"itemType": itemType, "title": title,
                                  "publicationTitle": "数字人文研究", "date": "2026"}}


def _article(title: str) -> Article:
    return Article(
        journal="数字人文研究", year=2026, volume=6, issue=2,
        title=title, articleUrl="http://example.com/a",
    )


class DuplicateCheckTests(unittest.TestCase):
    """查重必须翻页并归一化比较，否则会漏判导致重复导入 Zotero。"""

    def testFindsMatchBeyondFirstPage(self):
        client, fake = buildClient(autoCreate=False)
        # 命中项排在第 51 位：旧的 limit=10 首页扫描会漏掉它。
        fake.existing = [_item(f"F{i}", f"填充标题{i}") for i in range(50)]
        fake.existing.append(_item("DUP", "数字人文中的形式化偏向"))
        self.assertEqual(client.checkDuplicate(_article("数字人文中的形式化偏向")), "DUP")

    def testNormalizedTitleMatchesAcrossPunctuation(self):
        client, fake = buildClient(autoCreate=False)
        fake.existing = [_item("DUP", "“数字人文”（A—B）")]
        self.assertEqual(client.checkDuplicate(_article('"数字人文"(A-B)')), "DUP")

    def testIgnoresNonJournalArticleItems(self):
        client, fake = buildClient(autoCreate=False)
        fake.existing = [
            _item("BOOK", "数字人文中的形式化偏向", itemType="book"),
            _item("DUP", "数字人文中的形式化偏向", itemType="journalArticle"),
        ]
        self.assertEqual(client.checkDuplicate(_article("数字人文中的形式化偏向")), "DUP")

    def testReturnsNoneWhenNoMatch(self):
        client, fake = buildClient(autoCreate=False)
        fake.existing = [_item("X", "完全不同的标题")]
        self.assertIsNone(client.checkDuplicate(_article("数字人文中的形式化偏向")))

    def testScanIsCapped(self):
        client, fake = buildClient(autoCreate=False)
        # 匹配项落在扫描上限之外：宁可漏判也不把整库翻下来（病态宽命中的安全阀）。
        fake.existing = [_item(f"F{i}", f"填充{i}") for i in range(client.DUPLICATE_SCAN_LIMIT)]
        fake.existing.append(_item("FAR", "数字人文中的形式化偏向"))
        self.assertIsNone(client.checkDuplicate(_article("数字人文中的形式化偏向")))


class _RaisingCollectionsZot(FakeZot):
    """目录列表请求本身失败（400 Invalid user ID 就是这个形态）。"""

    def everything(self, _iterator):
        raise RuntimeError("HTTP Error 400: Invalid user ID")


class CollectionReadErrorTests(unittest.TestCase):
    def testReadFailureIsRecordedSeparatelyFromMissingPath(self):
        client = ZoteroClient({"webLibraryId": "1", "webApiKey": "key",
                               "collectionPath": ["10-研究相关"], "journalCollections": {}})
        client._zot = _RaisingCollectionsZot()

        self.assertIsNone(client.locateJournalCollection("图书馆论坛"))
        self.assertIn("Invalid user ID", client.collectionReadError)

    def testNoReadErrorWhenListingSucceeds(self):
        client, _fake = buildClient(autoCreate=False)
        self.assertIsNone(client.locateJournalCollection("图书馆论坛"))
        self.assertIsNone(client.collectionReadError, "查不到路径不能被记成读不出来")


class _CreateFailsZot(FakeZot):
    """create_items 抛错或返回 failed 的假客户端；everything() 按次给不同结果。"""

    def __init__(self, error=None, failed=None, searchPages=None):
        super().__init__()
        self.error = error
        self.failed = failed
        self.searchPages = list(searchPages or [])
        self.createCalls = 0

    def everything(self, _iterator):
        return self.searchPages.pop(0) if self.searchPages else []

    def item_template(self, itemType):
        return {"itemType": itemType, "title": "", "creators": [], "tags": [], "collections": []}

    def create_items(self, _payload):
        self.createCalls += 1
        if self.error is not None:
            raise self.error
        return {"successful": {}, "failed": self.failed or {}}


class CreationFailureAttributionTests(unittest.TestCase):
    """一次写入失败要说清「是没写进去，还是写进去了但响应丢了」。

    2026-10-23 真实撞上：`POST /items` 抛 Server disconnected，报告写「创建条目失败」，
    重跑却报「标题已存在」——服务端其实提交成功了。
    """

    def _client(self, **kwargs):
        client = ZoteroClient({"webLibraryId": "1", "webApiKey": "key",
                               "collectionPath": ["10-研究相关"], "journalCollections": {}})
        fake = _CreateFailsZot(**kwargs)
        client._zot = fake
        return client, fake

    def testClassifyMarkers(self):
        cases = {
            RuntimeError("Server disconnected without sending a response."): ("connection", True),
            TimeoutError("The read operation timed out"): ("connection", True),
            RuntimeError("HTTP Error 403: Forbidden"): ("rejected", False),
            RuntimeError("HTTP Error 400: Invalid user ID"): ("rejected", False),
            ValueError("字段 schema 不匹配"): ("api", False),
        }
        for error, expected in cases.items():
            with self.subTest(error=str(error)):
                self.assertEqual(classifyCreationFailure(error), expected)

    def testDroppedResponseAfterCommitReportsExistingItem(self):
        article = _article("唐代元和文学基本创作生态的量化研究")
        client, fake = self._client(
            error=RuntimeError("Server disconnected without sending a response."),
            searchPages=[[], [_item("H5DMUPHC", article.title)]],
        )
        result = client.importArticle(article, collectionKey="COL")

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["key"], "H5DMUPHC")
        self.assertIn("响应中断", result["reason"])
        self.assertEqual(fake.createCalls, 1, "回查只能查重，不得再写一次")

    def testDroppedResponseWithNothingCreatedTellsUserToRerun(self):
        article = _article("数字人文方法论、人文伦理与批判性教育")
        client, _fake = self._client(
            error=RuntimeError("Server disconnected without sending a response."),
            searchPages=[[], []],
        )
        result = client.importArticle(article, collectionKey="COL")

        self.assertEqual(result["status"], "failed")
        self.assertIn("重跑", result["reason"])
        self.assertIn("disconnected", result["reason"], "要把真实异常带给使用者")

    def testRejectedCredentialsIsNamedAsCredentials(self):
        article = _article("计算批评：人文概念与数字方法")
        client, _fake = self._client(error=RuntimeError("HTTP Error 403: Invalid user ID"))
        result = client.importArticle(article, collectionKey="COL")

        self.assertEqual(result["status"], "failed")
        self.assertIn("拒绝写入", result["reason"])
        self.assertIn("userID", result["reason"])

    def testApiFailureKeepsServerDetail(self):
        article = _article("系列笔谈之四：智能时代古籍OCR技术")
        client, _fake = self._client(failed={"0": {"code": "validation_failed", "message": "bad date"}})
        result = client.importArticle(article, collectionKey="COL")

        self.assertEqual(result["status"], "failed")
        self.assertIn("validation_failed", result["reason"])
        self.assertNotIn("路径不存在", result["reason"])


class FakeAttachZot:
    """只实现附件挂载所需调用的假客户端，可注入上传失败。"""

    def __init__(self, upload_error=None, upload_result=None):
        self.upload_error = upload_error
        self.upload_result = upload_result
        self.created: list[dict] = []
        self.uploaded: list[dict] = []
        self.deleted: list[dict] = []

    def item_template(self, item_type):
        return {
            "itemType": item_type, "title": "", "parentItem": "",
            "linkMode": "linked_file", "contentType": "", "charset": "",
            "filename": "", "url": "", "note": "", "tags": [],
        }

    def create_items(self, payload):
        entry = dict(payload[0])
        entry["key"] = f"ATT{len(self.created)}"
        entry["version"] = 42
        self.created.append(entry)
        return {"successful": {"0": entry}, "failed": {}}

    def upload_attachments(self, attachments, parentid=None, basedir=None):
        self.uploaded.extend(attachments)
        if self.upload_error:
            raise self.upload_error
        return self.upload_result

    def delete_item(self, payload, last_modified=None):
        self.deleted.append(payload)
        return True


class AttachPdfRollbackTests(unittest.TestCase):
    """上传失败必须回滚刚创建的附件记录。

    真实事故：配额满时 pyzotero 先创建记录、再在上传步骤抛异常，记录留在云端
    但文件不存在，桌面端同步后打开报「找不到文件」。
    """

    def setUp(self):
        import os
        import tempfile
        fd, self.pdfPath = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

    def tearDown(self):
        import os
        os.unlink(self.pdfPath)

    def _client(self, fake):
        client = ZoteroClient({"webLibraryId": "1", "webApiKey": "k"})
        client._zot = fake
        return client

    def testUploadExceptionRollsBackCreatedRecord(self):
        fake = FakeAttachZot(upload_error=Exception("File would exceed quota (301.8 > 300)"))
        ok = self._client(fake).attachPdf("PARENT1", self.pdfPath)
        self.assertFalse(ok)
        self.assertEqual([d["key"] for d in fake.deleted], ["ATT0"])

    def testUploadRejectedResultRollsBackCreatedRecord(self):
        fake = FakeAttachZot(upload_result={"success": [], "failure": [{"key": "ATT0"}], "unchanged": []})
        ok = self._client(fake).attachPdf("PARENT1", self.pdfPath)
        self.assertFalse(ok)
        self.assertEqual([d["key"] for d in fake.deleted], ["ATT0"])

    def testUploadSuccessKeepsRecord(self):
        fake = FakeAttachZot(upload_result={"success": [{"key": "ATT0"}], "failure": [], "unchanged": []})
        ok = self._client(fake).attachPdf("PARENT1", self.pdfPath)
        self.assertTrue(ok)
        self.assertEqual(fake.deleted, [])

    def testUnchangedCountsAsAttached(self):
        fake = FakeAttachZot(upload_result={"success": [], "failure": [], "unchanged": [{"key": "ATT0"}]})
        ok = self._client(fake).attachPdf("PARENT1", self.pdfPath)
        self.assertTrue(ok)
        self.assertEqual(fake.deleted, [])

    def testCreatePayloadUsesBasenameAndImportedMode(self):
        # 服务端拒绝 filename 含目录路径，创建用的必须是 basename
        import os
        fake = FakeAttachZot(upload_result={"success": [{"key": "ATT0"}], "failure": [], "unchanged": []})
        self._client(fake).attachPdf("PARENT1", self.pdfPath)
        created = fake.created[0]
        self.assertEqual(created["filename"], os.path.basename(self.pdfPath))
        self.assertEqual(created["linkMode"], "imported_file")
        self.assertEqual(created["parentItem"], "PARENT1")

    def testUploadPayloadCarriesFullPath(self):
        # 上传步骤要能读到原文件，filename 必须是完整路径
        fake = FakeAttachZot(upload_result={"success": [{"key": "ATT0"}], "failure": [], "unchanged": []})
        self._client(fake).attachPdf("PARENT1", self.pdfPath)
        self.assertEqual(fake.uploaded[0]["filename"], self.pdfPath)
        self.assertEqual(fake.uploaded[0]["key"], "ATT0")


if __name__ == "__main__":
    unittest.main()
