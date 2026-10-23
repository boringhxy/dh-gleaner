"""上手相关命令用例：init-collections / init / saveCredentials。

锁住三条关键行为：
1. `planCollections` 只读——绝不触发建目录；
2. `init-collections` 默认只预览，加 `--yes` 才写 Zotero；
3. `saveCredentials` 只写 config.local.json、收紧权限、覆盖前备份；
4. `init` 在非交互环境不阻塞提问，改为打印手动步骤。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

import dhgleaner.cli as cli_module
from dhgleaner.config import loadConfig
from dhgleaner.service import (
    CollectionPlanRow,
    CollectionsReport,
    ensureCollections,
    planCollections,
    saveCredentials,
)

try:
    from .helpers import tempDataDir
except ImportError:  # 直接以脚本方式运行时
    from helpers import tempDataDir

CFG = {"zotero": {}, "journals": [{"name": "图书馆论坛"}, {"name": "数字人文研究"}]}
PLANS = {
    "图书馆论坛": {
        "path": ["10-研究相关", "数字人文", "《图书馆论坛》"],
        "missing": ["《图书馆论坛》"],
        "resolvedKey": "C2",
        "error": None,
    },
    "数字人文研究": {
        "path": ["10-研究相关", "数字人文", "《数字人文研究》"],
        "missing": [],
        "resolvedKey": "C9",
        "error": None,
    },
}


class FakeCollectionsZotero:
    def __init__(self, plans=None, connected=True):
        self._plans = plans or {}
        self._connected = connected
        self.createdCollections: list[str] = []
        self.locateCalls: list[tuple] = []

    def testConnection(self):
        return self._connected

    def collectionPlan(self, journalName):
        return self._plans.get(
            journalName, {"path": [], "missing": [], "resolvedKey": None, "error": None}
        )

    def locateJournalCollection(self, journalName, createIfMissing=None):
        self.locateCalls.append((journalName, createIfMissing))
        if createIfMissing:
            for name in self.collectionPlan(journalName).get("missing", []):
                if name not in self.createdCollections:
                    self.createdCollections.append(name)
        return "COL"


class PlanCollectionsTests(unittest.TestCase):
    def testPlanIsReadOnlyAndNeverCreates(self):
        fake = FakeCollectionsZotero(PLANS)
        report = planCollections(CFG, zotero=fake)
        self.assertTrue(report.connected)
        self.assertEqual(len(report.rows), 2)
        self.assertEqual([r.journal for r in report.missingRows], ["图书馆论坛"])
        self.assertEqual(fake.locateCalls, [], "只读预检不得调用 locate/create")
        self.assertEqual(fake.createdCollections, [])

    def testConnectionFailureYieldsEmptyReport(self):
        fake = FakeCollectionsZotero(PLANS, connected=False)
        report = planCollections(CFG, zotero=fake)
        self.assertFalse(report.connected)
        self.assertEqual(report.rows, [])
        self.assertIn("连接失败", report.connectionError)

    def testEnsureCreatesMissingLevels(self):
        fake = FakeCollectionsZotero(PLANS)
        created, recheck = ensureCollections(CFG, zotero=fake)
        self.assertEqual(created, ["《图书馆论坛》"])
        self.assertIn(("图书馆论坛", True), fake.locateCalls)
        self.assertIn(("数字人文研究", True), fake.locateCalls)
        self.assertTrue(recheck.connected)

    def testEnsureScopedToSingleJournal(self):
        fake = FakeCollectionsZotero(PLANS)
        created, _ = ensureCollections(CFG, journals=["数字人文研究"], zotero=fake)
        self.assertEqual([name for name, _ in fake.locateCalls], ["数字人文研究"])
        self.assertEqual(created, [])


class SaveCredentialsTests(unittest.TestCase):
    def testWritesConfigLocalOnlyWithTightPerms(self):
        with tempDataDir() as dataDir:
            ok, detail = saveCredentials("12345", "secretKey")
            self.assertTrue(ok)
            path = dataDir / "config.local.json"
            self.assertEqual(Path(detail).resolve(), path.resolve())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["zotero"]["webLibraryId"], "12345")
            self.assertEqual(data["zotero"]["webApiKey"], "secretKey")
            if sys.platform == "win32":
                # NTFS 不保存 POSIX 权限位（`os.chmod` 在那里只落到「只读」属性上），
                # Windows 保护凭据靠的是账户隔离而不是 0600，所以这条断言只对 POSIX 有意义。
                self.skipTest("NTFS 没有 POSIX 权限位，0o600 断言仅适用于 POSIX 平台")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((dataDir / "config.json").exists(), "凭据绝不能写进 config.json")

    def testExistingConfigIsBackedUpBeforeOverwrite(self):
        with tempDataDir() as dataDir:
            saveCredentials("1", "a")
            ok, _ = saveCredentials("2", "b")
            self.assertTrue(ok)
            self.assertEqual(len(list(dataDir.glob("config.local.bak-*.json"))), 1)
            data = json.loads((dataDir / "config.local.json").read_text(encoding="utf-8"))
            self.assertEqual(data["zotero"]["webLibraryId"], "2")


class InitCollectionsCliTests(unittest.TestCase):
    def _run(self, args, report, ensureResult=None):
        calls = {"ensure": 0}
        originalPlan = cli_module.planCollections
        originalEnsure = cli_module.ensureCollections

        def fakeEnsure(cfg, journals=None):
            calls["ensure"] += 1
            return ensureResult or ([], report)

        cli_module.planCollections = lambda cfg: report
        cli_module.ensureCollections = fakeEnsure
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cli_module.cmdInitCollections(args, {"zotero": {}, "journals": []})
        finally:
            cli_module.planCollections = originalPlan
            cli_module.ensureCollections = originalEnsure
        return buf.getvalue(), calls["ensure"]

    def testPreviewByDefaultDoesNotCreate(self):
        report = CollectionsReport(connected=True, rows=[
            CollectionPlanRow(journal="图书馆论坛", path=["A", "B"], missing=["B"], resolvedKey="C1"),
        ])
        out, ensureCalls = self._run(
            type("Args", (), {"journal": None, "yes": False})(), report
        )
        self.assertIn("预检", out)
        self.assertIn("init-collections --yes", out)
        self.assertEqual(ensureCalls, 0, "默认必须只预览、不写 Zotero")

    def testYesFlagCreates(self):
        report = CollectionsReport(connected=True, rows=[
            CollectionPlanRow(journal="图书馆论坛", path=["A", "B"], missing=["B"], resolvedKey="C1"),
        ])
        recheck = CollectionsReport(connected=True, rows=[
            CollectionPlanRow(journal="图书馆论坛", path=["A", "B"], missing=[], resolvedKey="C2"),
        ])
        out, ensureCalls = self._run(
            type("Args", (), {"journal": None, "yes": True})(), report, ensureResult=(["B"], recheck)
        )
        self.assertEqual(ensureCalls, 1)
        self.assertIn("已新建", out)

    def testAllReadyNeedsNoCreation(self):
        report = CollectionsReport(connected=True, rows=[
            CollectionPlanRow(journal="图书馆论坛", path=["A", "B"], missing=[], resolvedKey="C1"),
        ])
        out, ensureCalls = self._run(
            type("Args", (), {"journal": None, "yes": True})(), report
        )
        self.assertIn("已就绪", out)
        self.assertEqual(ensureCalls, 0)

    def testPrecheckErrorIsNotReportedAsReady(self):
        """预检失败（如 400 Invalid user ID）时 missing 是空的，不能因此宣布「都已就绪」，更不能建目录。"""
        report = CollectionsReport(connected=True, rows=[
            CollectionPlanRow(journal="数字人文研究", path=["A", "B"], missing=[], error="HTTP 400 Invalid user ID"),
        ])
        out, ensureCalls = self._run(
            type("Args", (), {"journal": None, "yes": True})(), report
        )
        self.assertIn("预检失败", out)
        self.assertNotIn("都已就绪", out)
        self.assertEqual(ensureCalls, 0, "凭据出错时不得凭「无缺口」写库")

    def testConnectionFailurePrintsHint(self):
        report = CollectionsReport(connected=False, connectionError="Zotero 连接失败或凭据未配置")
        out, ensureCalls = self._run(
            type("Args", (), {"journal": None, "yes": False})(), report
        )
        self.assertIn("连接失败", out)
        self.assertEqual(ensureCalls, 0)


class InitWizardCliTests(unittest.TestCase):
    def testNonInteractivePrintsManualStepsWithoutBlocking(self):
        original = cli_module._isInteractive
        cli_module._isInteractive = lambda: False
        buf = io.StringIO()
        try:
            with tempDataDir():
                with contextlib.redirect_stdout(buf):
                    cli_module.cmdInit(type("Args", (), {})(), loadConfig())
        finally:
            cli_module._isInteractive = original
        out = buf.getvalue()
        self.assertIn("非交互环境", out)
        self.assertIn("config.local.json", out)
        self.assertIn("环境自检", out)


if __name__ == "__main__":
    unittest.main()
