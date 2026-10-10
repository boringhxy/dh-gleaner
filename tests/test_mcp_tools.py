"""MCP 工具层用例。

重点不是「返回字段长什么样」，而是两条安全属性：

1. 只读工具真的只读；
2. `import_to_zotero` 在未获显式确认时**连 runImport 都不会被调用**
   （用 monkeypatch 断言调用次数，而不是只看返回值）。
"""

from __future__ import annotations

import importlib.util
import unittest

try:
    from .helpers import pendingPayload, tempDataDir, writePending
except ImportError:
    from helpers import pendingPayload, tempDataDir, writePending

from dhgleaner.mcp import tools_capture, tools_import, tools_read
from dhgleaner.mcp.errors import KIND_BLOCKED, KIND_CAPTCHA, KIND_NETWORK, classifyFailure
from dhgleaner.mcp.server import buildServer
from dhgleaner.service import loadPending

# buildServer() 会惰性 import mcp；未装 mcp 依赖时只跳过这一条注册校验，
# 其余工具层用例（纯 dict 逻辑）照常运行，保证本地 `pip install -e '.[dev]'` 即可跑测试。
_MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

ARTICLES = [
    {
        "journal": "数字人文研究",
        "year": 2026,
        "volume": 6,
        "issue": 2,
        "title": "数字人文中的形式化偏向",
        "authors": ["赵皓玥"],
        "abstract": "摘要文本",
        "articleUrl": "http://example.com/a",
        "pdfUrl": "http://example.com/a.pdf",
        "_globalIndex": 1,
    },
    {
        "journal": "图书馆论坛",
        "year": 2026,
        "volume": 46,
        "issue": 3,
        "title": "图书馆的数字人文服务实践",
        "authors": ["钱五"],
        "abstract": "",
        "articleUrl": "http://example.com/b",
        "pdfUrl": "",
        "_globalIndex": 2,
    },
]


EXPECTED_TOOLS = {
    "list_journals",
    "get_capture_status",
    "list_pending_articles",
    "get_article_abstract",
    "search_pending_articles",
    "preview_import",
    "get_import_report",
    "run_doctor",
    "capture_issue",
    "capture_channel",
    "export_review_spreadsheet",
    "mark_pending_skipped",
    "import_to_zotero",
}


class RegistrationTests(unittest.TestCase):
    @unittest.skipUnless(_MCP_AVAILABLE, "需要 mcp 依赖（pip install -e '.[mcp]'）才能构建 server")
    def testAllThirteenToolsAreRegistered(self):
        server = buildServer()
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertEqual(names, EXPECTED_TOOLS)

    def testImportToolIsTheOnlyZoteroWriter(self):
        """命名可读性：只有 import_to_zotero 读起来像写库工具。"""
        writers = {name for name in EXPECTED_TOOLS if name.startswith("import_to")}
        self.assertEqual(writers, {"import_to_zotero"})


class FailureClassificationTests(unittest.TestCase):
    def testStatusCodesAndCaptcha(self):
        self.assertEqual(classifyFailure("站点拒绝访问（HTTP 412）"), KIND_BLOCKED)
        self.assertEqual(classifyFailure("HTTP 403 Forbidden"), KIND_BLOCKED)
        self.assertEqual(classifyFailure("该页需要验证码"), KIND_CAPTCHA)

    def testNetworkMarkers(self):
        self.assertEqual(classifyFailure("抓取失败 [3/3] ...: Read timed out"), KIND_NETWORK)


class ReadToolTests(unittest.TestCase):
    def testListJournalsDescribesLimits(self):
        result = tools_read.listJournals()
        self.assertTrue(result["ok"])
        names = [journal["name"] for journal in result["journals"]]
        self.assertIn("图书馆论坛", names)
        self.assertEqual(len(names), 6)
        cnki = next(j for j in result["journals"] if j["name"] == "数字人文")
        self.assertIn("验证码", cnki["pdfNote"])

    def testPendingToolsReportNoPendingInsteadOfCrashing(self):
        with tempDataDir():
            self.assertFalse(tools_read.listPendingArticles()["ok"])
            self.assertEqual(tools_read.listPendingArticles()["failureKind"], "no_pending")
            self.assertFalse(tools_read.searchPendingArticles("数字人文")["ok"])
            self.assertFalse(tools_read.getArticleAbstract(1)["ok"])

    def testListAndFilterPendingArticles(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            everything = tools_read.listPendingArticles()
            self.assertEqual(everything["total"], 2)

            onlyTsglt = tools_read.listPendingArticles(journal="图书馆论坛")
            self.assertEqual(onlyTsglt["total"], 1)
            self.assertEqual(onlyTsglt["articles"][0]["title"], "图书馆的数字人文服务实践")
            self.assertNotIn("articleUrl", onlyTsglt["articles"][0])  # includeUrls 默认关

            paged = tools_read.listPendingArticles(limit=1, offset=1)
            self.assertEqual(paged["total"], 2)
            self.assertEqual(paged["returned"], 1)
            self.assertEqual(paged["articles"][0]["index"], 2)

    def testAbstractByIndex(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            found = tools_read.getArticleAbstract(1)
            self.assertTrue(found["ok"])
            self.assertEqual(found["abstract"], "摘要文本")

            missing = tools_read.getArticleAbstract(99)
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["failureKind"], "invalid_input")

    def testSearchPendingArticles(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_read.searchPendingArticles("形式化")
            self.assertTrue(result["ok"])
            self.assertEqual(result["total"], 1)

    def testPreviewImportIsReadOnly(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            preview = tools_read.previewImport(selection="2")
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["status"], "resolved")
            self.assertEqual(preview["count"], 1)
            self.assertEqual(preview["articles"][0]["index"], 2)

            markdown, articles = loadPending()
            self.assertEqual([a.status for a in articles], ["new", "new"])  # 未落盘

    def testPreviewImportRequiresSomeScope(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_read.previewImport()
            self.assertFalse(result["ok"])
            self.assertEqual(result["failureKind"], "invalid_input")

    def testRunDoctorReportsChecks(self):
        with tempDataDir():
            report = tools_read.runDoctor()
            self.assertTrue(report["ok"])
            labels = [c["label"] for c in report["checks"]]
            self.assertIn("Python 版本", labels)
            self.assertIn("你自己的 Zotero 凭据", labels)


class ImportGateTests(unittest.TestCase):
    """双重闸门的核心断言：没确认就绝不触碰 runImport。"""

    def setUp(self):
        self.calls = []
        self.abort = False
        self._original = tools_import.runImport

        def fakeRunImport(selected, articles, markdown, cfg, **kwargs):
            self.calls.append([a.title for a in selected])
            from dhgleaner.service import ImportOutcome

            if self.abort:
                return ImportOutcome(
                    report="# 导入报告\n\n## ⚠️ Zotero 连接失败",
                    reportPath=None,
                    selectedCount=len(selected),
                    aborted=True,
                    abortReason="Zotero 连接失败，未写入任何条目",
                )
            return ImportOutcome(
                report="# 导入报告",
                reportPath=None,
                selectedCount=len(selected),
                imported=len(selected),
            )

        tools_import.runImport = fakeRunImport

    def tearDown(self):
        tools_import.runImport = self._original

    def testNoConfirmationMeansRefusedAndNoWrite(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_import.importToZotero(selection="1")
            self.assertTrue(result["ok"])
            self.assertTrue(result["refused"])
            self.assertTrue(result["requiresConfirmation"])
            self.assertEqual(result["count"], 1)
            self.assertEqual(self.calls, [])

    def testConfirmWithoutDryRunFalseIsStillRefused(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_import.importToZotero(selection="1", confirm=True)  # dryRun 仍为 True
            self.assertTrue(result["refused"])
            self.assertIn("dryRun=false", result["note"])
            self.assertEqual(self.calls, [])

    def testBothGatesOpenWritesOnce(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_import.importToZotero(selection="1", confirm=True, dryRun=False)
            self.assertTrue(result["ok"])
            self.assertNotIn("refused", result)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(self.calls, [["数字人文中的形式化偏向"]])

    def testInvalidScopeIsRejectedBeforeAnyGate(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_import.importToZotero(selection="999", confirm=True, dryRun=False)
            self.assertFalse(result["ok"])
            self.assertEqual(self.calls, [])

    def testImportReportsCollectionPlan(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_import.importToZotero(selection="1")
            plan = result["collectionPlan"]
            self.assertIn("autoCreateCollection", plan)
            self.assertIn("数字人文研究", plan["journals"])

    def testAbortedImportIsNotReportedAsSuccess(self):
        """凭据缺失时报告会说「连接失败」，工具就不能回一句 imported=N 蒙混过去。"""
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            self.abort = True
            result = tools_import.importToZotero(selection="1", confirm=True, dryRun=False)
            self.assertFalse(result["ok"])
            self.assertTrue(result["wroteNothing"])
            self.assertEqual(result["imported"], 0)
            self.assertEqual(result["failureKind"], "not_configured")


class LocalWriteToolTests(unittest.TestCase):
    def testExportSpreadsheetWritesIntoDataDir(self):
        with tempDataDir() as dataDir:
            writePending(pendingPayload(ARTICLES))
            result = tools_capture.exportReviewSpreadsheet()
            self.assertTrue(result["ok"])
            self.assertTrue((dataDir / "data" / "review_selection.xlsx").exists())

    def testExportSpreadsheetWithoutPending(self):
        with tempDataDir():
            result = tools_capture.exportReviewSpreadsheet()
            self.assertFalse(result["ok"])
            self.assertEqual(result["failureKind"], "no_pending")

    def testMarkSkippedRequiresConfirmation(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            refused = tools_capture.markPendingSkipped()
            self.assertFalse(refused["ok"])
            self.assertTrue(refused["refused"])

            _, articles = loadPending()
            self.assertEqual([a.status for a in articles], ["new", "new"])

    def testMarkSkippedMarksStateWhenConfirmed(self):
        with tempDataDir():
            writePending(pendingPayload(ARTICLES))
            result = tools_capture.markPendingSkipped(confirm=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["skippedCount"], 2)

            _, articles = loadPending()
            self.assertEqual([a.status for a in articles], ["presented", "presented"])

    def testCaptureIssueRejectsUnknownJournal(self):
        with tempDataDir():
            result = tools_capture.captureIssue(journal="不存在的刊", year=2026, issue=1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failureKind"], "invalid_input")

    def testCaptureIssueRequiresScope(self):
        with tempDataDir():
            result = tools_capture.captureIssue(journal="图书馆论坛")
            self.assertFalse(result["ok"])
            self.assertEqual(result["failureKind"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
