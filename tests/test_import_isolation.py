"""导入的失败路径必须零副作用。

回归背景
--------
`runImport` 早期无条件执行 `savePending`，于是「Zotero 凭据没配好」这种
最普通的失败场景也会改写本地状态：刷新 `pending.json` 的 `capturedAt`，
并把已经标记为 `presented` 的文章打回 `selected`——已经看过（甚至已经导入）
的文献会重新冒回待筛清单。

本文件把这个安全属性钉死：**预检中止 = 一个字都不落盘**。
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

try:
    from .helpers import pendingPayload, tempDataDir, writePending
except ImportError:  # 直接以脚本方式运行时
    from helpers import pendingPayload, tempDataDir, writePending

import dhgleaner.service as service_module
from dhgleaner import paths as paths_module
from dhgleaner.service import loadPending, runImport

UA = "Mozilla/5.0"

# 两篇「已经给用户看过」的文章。失败路径若误改 pending，status 会退回 selected。
PRESENTED_ARTICLES = [
    {
        "journal": "数字人文研究",
        "year": 2026,
        "volume": 6,
        "issue": 2,
        "title": "数字人文中的形式化偏向",
        "authors": ["赵皓玥"],
        "status": "presented",
        "_globalIndex": 1,
    },
    {
        "journal": "图书馆论坛",
        "year": 2026,
        "volume": 46,
        "issue": 3,
        "title": "图书馆的数字人文服务实践",
        "authors": ["钱五"],
        "status": "presented",
        "_globalIndex": 2,
    },
]


def _cfg() -> dict:
    return {"zotero": {}, "journals": [], "http": {"userAgent": UA}}


def _digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class _UnreachableZotero:
    """连不上（最典型场景：用户还没配 config.local.json）。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def testConnection(self) -> bool:
        return False


class _NoCollectionZotero:
    """连得上，但目标 Collection 不存在。"""

    createdCollections: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def testConnection(self) -> bool:
        return True

    def locateJournalCollection(self, journalName: str):
        return None


class ImportAbortLeavesNoTraceTests(unittest.TestCase):
    def setUp(self):
        self._original = service_module.ZoteroClient

    def tearDown(self):
        service_module.ZoteroClient = self._original

    def _snapshot(self) -> dict:
        paths = paths_module.getPaths()
        return {"pending": _digest(paths.pending), "review": _digest(paths.review)}

    def _seed(self) -> None:
        writePending(pendingPayload(PRESENTED_ARTICLES))
        paths_module.getPaths().review.write_text("# 旧清单\n", encoding="utf-8")

    def testCredentialMissingAbortKeepsLocalStateIntact(self):
        service_module.ZoteroClient = _UnreachableZotero
        with tempDataDir():
            self._seed()
            before = self._snapshot()

            markdown, articles = loadPending()
            outcome = runImport(articles, articles, markdown, _cfg())

            self.assertTrue(outcome.aborted)
            self.assertIn("连接失败", outcome.abortReason)
            self.assertEqual(outcome.imported, 0)
            self.assertEqual(self._snapshot(), before)

    def testMissingCollectionAbortKeepsLocalStateIntact(self):
        service_module.ZoteroClient = _NoCollectionZotero
        with tempDataDir():
            self._seed()
            before = self._snapshot()

            markdown, articles = loadPending()
            outcome = runImport(articles, articles, markdown, _cfg())

            self.assertTrue(outcome.aborted)
            self.assertEqual(outcome.imported, 0)
            self.assertEqual(self._snapshot(), before)

    def testNothingSelectedAbortKeepsLocalStateIntact(self):
        service_module.ZoteroClient = _UnreachableZotero
        with tempDataDir():
            self._seed()
            before = self._snapshot()

            markdown, articles = loadPending()
            outcome = runImport([], articles, markdown, _cfg())

            self.assertTrue(outcome.aborted)
            self.assertEqual(self._snapshot(), before)

    def testAbortReportsNothingWrittenAndNoReportFile(self):
        """中止时不写 import_report.md——`wroteNothing` 必须名副其实。"""
        service_module.ZoteroClient = _UnreachableZotero
        with tempDataDir() as root:
            self._seed()

            markdown, articles = loadPending()
            outcome = runImport(articles, articles, markdown, _cfg())

            self.assertIsNone(outcome.reportPath)
            self.assertFalse((root / "data" / "import_report.md").exists())
            # 诊断信息仍在返回值里，没有因为不落盘而丢失
            self.assertIn("连接失败", outcome.report)


if __name__ == "__main__":
    unittest.main()
