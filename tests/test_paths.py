"""数据目录解析用例 —— 锁定优先级与产物布局。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dhjournal import paths


class ResolveDataDirTests(unittest.TestCase):
    def testCliWins(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, source = paths.resolveDataDir(tmp)
            self.assertEqual(directory, Path(tmp).resolve())
            self.assertEqual(source, paths.SOURCE_CLI)

    def testEnvBeatsLegacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {paths.ENV_DATA_DIR: tmp}):
                directory, source = paths.resolveDataDir()
            self.assertEqual(directory, Path(tmp).resolve())
            self.assertEqual(source, paths.SOURCE_ENV)

    def testLegacyDetectsProjectRoot(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").write_text("{}", encoding="utf-8")
            with mock.patch.dict(os.environ, {paths.ENV_DATA_DIR: ""}):
                with mock.patch("pathlib.Path.cwd", return_value=Path(tmp)):
                    directory, source = paths.resolveDataDir()
            self.assertEqual(directory, Path(tmp).resolve())
            self.assertEqual(source, paths.SOURCE_LEGACY)

    def testLegacyDetectsDataDir(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            with mock.patch.dict(os.environ, {paths.ENV_DATA_DIR: ""}):
                with mock.patch("pathlib.Path.cwd", return_value=Path(tmp)):
                    _, source = paths.resolveDataDir()
            self.assertEqual(source, paths.SOURCE_LEGACY)

    def testDefaultFallsBackToHome(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {paths.ENV_DATA_DIR: ""}):
                with mock.patch("pathlib.Path.cwd", return_value=Path(tmp)):
                    directory, source = paths.resolveDataDir()
            self.assertEqual(source, paths.SOURCE_DEFAULT)
            self.assertEqual(directory, Path.home() / paths.DEFAULT_DIR_NAME)


class PathsLayoutTests(unittest.TestCase):
    def testArtifactsLiveUnderDataDir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with paths.useDataDir(tmp) as current:
                self.assertEqual(current.pending, root / "data" / "pending.json")
                self.assertEqual(current.review, root / "data" / "review.md")
                self.assertEqual(current.spreadsheet, root / "data" / "review_selection.xlsx")
                self.assertEqual(current.backupDir, root / "data" / "backups")
                self.assertEqual(current.defaultStateFile, root / "data" / "state.json")
                self.assertEqual(current.defaultTempDir, root / "tmp")
                self.assertEqual(current.defaultLogFile, root / "logs" / "capture.log")
                self.assertEqual(current.configLocalPath, root / "config.local.json")

    def testUseDataDirRestoresPrevious(self):
        before = paths.getPaths().dataDir
        with tempfile.TemporaryDirectory() as tmp:
            with paths.useDataDir(tmp):
                self.assertNotEqual(paths.getPaths().dataDir, before)
        self.assertEqual(paths.getPaths().dataDir, before)

    def testPackageTemplateExists(self):
        self.assertTrue(paths.configTemplatePath().is_file())
        self.assertTrue(paths.defaultConfigPath().is_file())


if __name__ == "__main__":
    unittest.main()
