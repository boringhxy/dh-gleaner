"""Zotero 客户端用例 —— 重点是 autoCreateCollection 开关的真实行为。"""

from __future__ import annotations

import unittest

from dhjournal.models import Article
from dhjournal.zotero_client import ZoteroClient


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
    return {"key": key, "data": {"itemType": itemType, "title": title}}


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


if __name__ == "__main__":
    unittest.main()
