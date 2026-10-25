"""Release blockers: reproduce real failures with isolated files and fake services."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dhgleaner import paths, service
from dhgleaner.config import loadConfig
from dhgleaner.importer import ImportSummary
from dhgleaner.mcp import tools_capture, tools_import
from dhgleaner.models import Article, IssueInfo
from dhgleaner.review_spreadsheet import exportReviewSpreadsheet, loadSpreadsheetSelection
from dhgleaner.selection import resolveAll, resolveBySelection, resolveByTitlesFromList, resolveSkipAll
from dhgleaner.state import StateManager
from dhgleaner.zotero_client import ZoteroClient


def article(index=1):
    item = Article(journal="数字人文研究", year=2026, volume=6, issue=2,
                   title=f"用于摘要筛选的测试文章{index}", abstract="离线测试摘要",
                   articleUrl=f"https://example.org/{index}")
    item._globalIndex = index
    return item


class ReleasePersistenceTests(unittest.TestCase):
    def testCredentialBackupsAreIgnored(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            service.saveCredentials("123", "FAKE_FIRST")
            service.saveCredentials("123", "FAKE_SECOND")
            backups = list(Path(tmp).glob("config.local.bak-*.json"))
            self.assertEqual(len(backups), 1)
            repo = Path(__file__).resolve().parents[1]
            result = subprocess.run(["git", "check-ignore", "--no-index", backups[0].name],
                                    cwd=repo, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, "credential backups must never be staged")

    def testFailedPendingCommitIsNotReportedAsSuccess(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            service.savePending("OLD", [article()])
            pending = paths.getPaths().pending
            old = pending.read_bytes()
            outcome = service.CaptureOutcome(journal="数字人文研究", issue="2026年第2期",
                                             markdown="NEW", articles=[article(2)],
                                             quality="success", status="success")
            replace = os.replace

            def denyPending(src, dst):
                if Path(dst) == pending:
                    raise PermissionError("simulated pending commit failure")
                return replace(src, dst)

            with patch("os.replace", side_effect=denyPending):
                result = service._finishCapture(outcome, captureType="issue", note="", dryRun=False)
            self.assertEqual(result.status, "failed")
            self.assertFalse(result.wrotePending)
            self.assertEqual(pending.read_bytes(), old)
            self.assertEqual(paths.getPaths().review.read_text(), "OLD")
            self.assertEqual(service.loadCaptureStatus()["status"], "failed")

    def testReviewWriteFailureKeepsBothOldArtifacts(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            service.savePending("OLD", [article()])
            pending = paths.getPaths().pending
            before = pending.read_bytes()
            replace = os.replace

            def denyReview(src, dst):
                if Path(dst) == paths.getPaths().review:
                    raise PermissionError("simulated review commit failure")
                return replace(src, dst)

            with patch("os.replace", side_effect=denyReview), self.assertRaises(OSError):
                service.savePending("NEW", [article(2)])
            self.assertEqual(pending.read_bytes(), before)
            self.assertEqual(paths.getPaths().review.read_text(), "OLD")

    def testImportRetryKeepsWorkbookAndCaptureIdentity(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            item = article()
            service.savePending("MD", [item], captureType="harvest", note="annual harvest")
            pending = paths.getPaths().pending
            data = json.loads(pending.read_text())
            data["capturedAt"] = "2000-01-01T00:00:00+08:00"
            pending.write_text(json.dumps(data))
            workbook = exportReviewSpreadsheet(Path(tmp) / "review.xlsx", [item], data, [1])
            summary = ImportSummary(report="failed remote write", attempted=1, failed=1)
            with patch("dhgleaner.service.importArticlesDetailed", return_value=summary):
                service.runImport([item], [item], "MD", loadConfig())
            after = service.loadPendingData()
            self.assertEqual(after["capturedAt"], data["capturedAt"])
            self.assertEqual(after["captureType"], "harvest")
            self.assertEqual(after["note"], "annual harvest")
            self.assertEqual(len(loadSpreadsheetSelection(workbook, [item], after)), 1)


class CompletedSelectionTests(unittest.TestCase):
    def testSelectingAnotherArticlePreservesImportedStatus(self):
        first, second = article(), article(2)
        first.status, first.zoteroKey = "imported", "ZOTERO1"
        resolveBySelection("2", [first, second])
        self.assertEqual(first.status, "imported")
        resolveAll([first, second])
        self.assertEqual(first.status, "imported")
        resolveByTitlesFromList([second.title], [first, second], confirm=True)
        self.assertEqual(first.status, "imported")

    def testSkipOnlyRemainingArticlesAndKeepRemoteKeys(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(str(Path(tmp) / "state.json"))
            first, second = article(), article(2)
            first.status, first.zoteroKey = "imported", "ZOTERO1"
            state.markArticleProcessed(first.journal, first.articleKey(), "ZOTERO1", first.title)
            outcome = resolveSkipAll([first, second], state)
            self.assertEqual(outcome.skippedCount, 1)
            meta = state.state["journals"][first.journal]["processedArticleMeta"][first.articleKey()]
            self.assertEqual(meta["zoteroKey"], "ZOTERO1")
            self.assertEqual(meta["status"], "imported")
            self.assertEqual(first.status, "imported")
            self.assertEqual(resolveSkipAll([first, second], state).skippedCount, 0)


class DuplicateIdentityTests(unittest.TestCase):
    def check(self, existing, incoming):
        client = ZoteroClient({})
        client._zot = Mock()
        client._zot.everything.return_value = [{"key": "EXISTING", "data": existing}]
        return client.checkDuplicate(incoming)

    def existing(self, **changes):
        return {"itemType": "journalArticle", "title": article().title,
                "publicationTitle": "数字人文研究", "date": "2026", **changes}

    def testConflictingDoiCannotBeDuplicate(self):
        item = article()
        item.doi = "10.1234/new"
        self.assertIsNone(self.check(self.existing(DOI="10.1234/old"), item))

    def testSameTitleDifferentJournalCannotBeDuplicate(self):
        self.assertIsNone(self.check(self.existing(publicationTitle="另一种期刊"), article()))

    def testSameTitleDifferentYearCannotBeDuplicate(self):
        self.assertIsNone(self.check(self.existing(date="2020"), article()))

    def testDoiUrlsAndCaseNormalize(self):
        item = article()
        item.doi = "10.1234/AbC"
        self.assertEqual(self.check(self.existing(DOI="https://doi.org/10.1234/abc"), item), "EXISTING")

    def testTitleAloneIsNotEnough(self):
        self.assertIsNone(self.check({"itemType": "journalArticle", "title": article().title}, article()))

    def testChineseYearDateIsRecognized(self):
        self.assertEqual(self.check(self.existing(date="2026年"), article()), "EXISTING")

    def testSameArticleUrlCanIdentifyMissingYear(self):
        item = article()
        item.year = 0
        self.assertEqual(self.check(self.existing(date="", url=item.articleUrl), item), "EXISTING")


class ReadOnlyCaptureTests(unittest.TestCase):
    def testCliDoctorDoesNotCreateLogOrDataDirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, "-B", "-m", "dhgleaner", "doctor", "--data-dir", tmp],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def testReadOnlyStateDoesNotQuarantineCorruptFile(self):
        with tempfile.TemporaryDirectory() as tmp:
            stateFile = Path(tmp) / "state.json"
            stateFile.write_text("broken json")
            state = StateManager(str(stateFile), readOnly=True)
            state.updateLastCheck("测试刊")
            self.assertEqual(stateFile.read_text(), "broken json")
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def testDryRunHarvestDoesNotCreateState(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            parser = Mock(supportsHarvest=True)
            parser.harvestYear.return_value = (IssueInfo(2026), [article()])
            with patch("dhgleaner.harvest.getParser", return_value=parser):
                result = service.captureHarvest(loadConfig(), year=2026, journalName="现代情报", dhOnly=False, dryRun=True)
            self.assertEqual(result.status, "success")
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def testMcpLimitIsHonored(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            outcome = service.CaptureOutcome(journal="数字人文研究", issue="2026年第2期",
                                             markdown="MD", articles=[article(), article(2)],
                                             quality="success", status="success")
            with patch("dhgleaner.mcp.tools_capture._captureIssue", return_value=outcome):
                result = tools_capture.captureIssue(journal="数字人文研究", year=2026, issue=2, limit=1)
            self.assertEqual(len(result["articles"]), 1)
            self.assertTrue(result["articlesTruncated"])

    def testDryRunCaptureDoesNotCreateAnyFiles(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            parser = Mock()
            parser.parseCurrentIssue.return_value = (IssueInfo(2026, 6, 2), [article()])
            parser.fetchAbstracts.side_effect = lambda items: items
            with patch("dhgleaner.capture.resolveIssueUrl", return_value="https://example.org/issue"), \
                 patch("dhgleaner.capture.fetchHtml", return_value="<html/>"), \
                 patch("dhgleaner.capture.getParser", return_value=parser):
                result = service.captureIssue(loadConfig(), journalName="数字人文研究",
                                              target={"year": 2026, "issue": 2}, dryRun=True)
            self.assertEqual(result.status, "success")
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def testDoctorDoesNotCreateDataDirectories(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            service.collectDoctorChecks(loadConfig())
            self.assertEqual(list(Path(tmp).rglob("*")), [])


class ImportReportingTests(unittest.TestCase):
    def testRemoteSuccessSurvivesStateWriteFailure(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            client = Mock()
            client.testConnection.return_value = True
            client.locateJournalCollection.return_value = "COLLECTION"
            client.collectionReadError = None
            client.createdCollections = []
            client.importArticle.return_value = {"status": "imported", "key": "REMOTE1"}
            item = article()
            service.savePending("MD", [item])
            with patch("dhgleaner.service.ZoteroClient", return_value=client), \
                 patch.object(StateManager, "_writeAtomic", side_effect=PermissionError("state is read-only")):
                result = service.runImport([item], [item], "MD", loadConfig())
            self.assertEqual(result.imported, 1)
            self.assertIn("state", result.localSaveError)
            self.assertEqual(service.loadPending()[1][0].zoteroKey, "REMOTE1")
            self.assertIsNotNone(result.reportPath)

    def testPreflightAbortDoesNotCreateTempDirectory(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            client = Mock()
            client.testConnection.return_value = False
            with patch("dhgleaner.service.ZoteroClient", return_value=client):
                result = service.runImport([article()], [article()], "MD", loadConfig())
            self.assertTrue(result.aborted)
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def testLocalFailureStillReportsRemoteSuccess(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            item = article()
            service.savePending("OLD", [item])
            summary = ImportSummary(report="Remote: imported 1", attempted=1, imported=1)
            with patch("dhgleaner.service.importArticlesDetailed", return_value=summary), \
                 patch("dhgleaner.service.savePending", side_effect=PermissionError("full disk")):
                result = service.runImport([item], [item], "OLD", loadConfig())
            self.assertEqual(result.imported, 1)
            self.assertFalse(result.aborted)
            self.assertIn("full disk", result.localSaveError)
            self.assertIn("Zotero 写入结果仍然有效", result.report)

    def testMcpDoesNotCallRemoteSuccessNothingWritten(self):
        with tempfile.TemporaryDirectory() as tmp, paths.useDataDir(tmp):
            service.savePending("MD", [article()])
            outcome = service.ImportOutcome(report="Remote: imported 1", imported=1, localSaveError="full disk")
            with patch("dhgleaner.mcp.tools_import._collectionPlan", return_value={}), \
                 patch("dhgleaner.mcp.tools_import.runImport", return_value=outcome):
                result = tools_import.importToZotero(selection="1", confirm=True, dryRun=False)
            self.assertFalse(result["ok"])
            self.assertFalse(result["wroteNothing"])
            self.assertEqual(result["imported"], 1)


class DirectoryOwnershipTests(unittest.TestCase):
    def testUnrelatedDataFolderDoesNotSelectLegacyMode(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            with patch.dict(os.environ, {paths.ENV_DATA_DIR: ""}), patch("pathlib.Path.cwd", return_value=Path(tmp)):
                _, source = paths.resolveDataDir()
            self.assertEqual(source, paths.SOURCE_DEFAULT)

    def testUnrelatedConfigDoesNotSelectLegacyMode(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").write_text('{"theme":"dark"}')
            with patch.dict(os.environ, {paths.ENV_DATA_DIR: ""}), patch("pathlib.Path.cwd", return_value=Path(tmp)):
                _, source = paths.resolveDataDir()
            self.assertEqual(source, paths.SOURCE_DEFAULT)
