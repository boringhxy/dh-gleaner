"""selection / service 层用例：解析结果、副作用边界与数据产物。

这些用例锁住的是「谁决定导入哪些文章」与「什么情况下不许写盘」，
与 tests/test_agent.py 的端到端用例形成互补。
"""

from __future__ import annotations

import json
import unittest

try:
    from .helpers import tempDataDir
except ImportError:  # 直接以脚本方式运行时
    from helpers import tempDataDir

from dhgleaner.models import STATUS_PRESENTED, STATUS_SELECTED, Article
from dhgleaner.selection import (
    STATUS_EMPTY,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIRM,
    STATUS_OK,
    STATUS_SKIP_ALL,
    STATUS_TITLE_CONFIRM_REQUIRED,
    resolveAll,
    resolveBySelection,
    resolveBySpreadsheet,
    resolveByTitlesFromList,
    resolveSkipAll,
)
from dhgleaner.selection_basket import loadBasket, pendingFingerprint
from dhgleaner.service import (
    loadCaptureStatus,
    loadPending,
    previewArticles,
    saveCaptureStatus,
    savePending,
    stateManager,
    writeTextArtifact,
)
from dhgleaner.validation import ValidationError, buildTarget, isSkipToken, normalizeJournalName


def makeArticles(titles: list[str]) -> list[Article]:
    articles = []
    for index, title in enumerate(titles, 1):
        article = Article(
            journal="数字人文研究",
            year=2026,
            volume=6,
            issue=2,
            title=title,
            articleUrl=f"http://example.com/{index}",
        )
        article._globalIndex = index
        articles.append(article)
    return articles


class ValidationTests(unittest.TestCase):
    def test_build_target_requires_year_and_issue(self):
        self.assertIsNone(buildTarget())
        self.assertEqual(buildTarget(2026, 2), {"year": 2026, "issue": 2})
        self.assertEqual(buildTarget(2026, 2, 6), {"year": 2026, "issue": 2, "volume": 6})
        with self.assertRaises(ValidationError):
            buildTarget(2026, None)
        with self.assertRaises(ValidationError):
            buildTarget(None, 2)

    def test_validation_error_is_not_system_exit(self):
        """校验失败必须是 ValidationError —— SystemExit 会杀掉 MCP 进程。"""
        self.assertFalse(issubclass(ValidationError, SystemExit))
        self.assertFalse(issubclass(ValidationError, SystemExit.__class__))

    def test_journal_alias_normalization(self):
        self.assertEqual(normalizeJournalName("tsglt"), "图书馆论坛")
        self.assertEqual(normalizeJournalName(" 數位典藏與數位人文 "), "数位典藏与数位人文")
        self.assertEqual(normalizeJournalName("dhr"), "数字人文研究")
        self.assertEqual(normalizeJournalName("未知刊"), "未知刊")

    def test_skip_tokens(self):
        self.assertTrue(isSkipToken("都不要"))
        self.assertTrue(isSkipToken(" none "))
        self.assertFalse(isSkipToken("1,3"))


class SelectionTests(unittest.TestCase):
    def test_resolve_by_selection_marks_only_chosen(self):
        articles = makeArticles(["甲", "乙", "丙"])
        outcome = resolveBySelection("1,3", articles)
        self.assertEqual(outcome.status, STATUS_OK)
        self.assertEqual([a.title for a in outcome.selected], ["甲", "丙"])
        self.assertEqual([a.status for a in articles], [STATUS_SELECTED, STATUS_PRESENTED, STATUS_SELECTED])

    def test_resolve_by_selection_unknown_index_is_empty(self):
        outcome = resolveBySelection("999", makeArticles(["甲"]))
        self.assertEqual(outcome.status, STATUS_EMPTY)
        self.assertEqual(outcome.selected, [])
        self.assertIn("未选中任何文章", outcome.message)

    def test_resolve_by_selection_skip_token(self):
        outcome = resolveBySelection("都不要", makeArticles(["甲"]))
        self.assertEqual(outcome.status, STATUS_SKIP_ALL)
        self.assertEqual(outcome.selected, [])

    def test_resolve_all_selects_everything(self):
        articles = makeArticles(["甲", "乙"])
        outcome = resolveAll(articles)
        self.assertEqual(outcome.status, STATUS_OK)
        self.assertEqual(len(outcome.selected), 2)

    def test_titles_without_confirm_requires_confirmation(self):
        articles = makeArticles(["基于地方志的空间数据整理", "从晚清民国报刊看城市文化"])
        outcome = resolveByTitlesFromList(["从晚清民国报刊看城市文化"], articles, confirm=False)
        self.assertEqual(outcome.status, STATUS_TITLE_CONFIRM_REQUIRED)
        self.assertEqual(outcome.selected, [])
        self.assertEqual(outcome.selectionHint, "2")

    def test_titles_with_confirm_keeps_user_order(self):
        articles = makeArticles(["基于地方志的空间数据整理", "从晚清民国报刊看城市文化"])
        outcome = resolveByTitlesFromList(
            ["从晚清民国报刊看城市文化", "基于地方志的空间数据整理"], articles, confirm=True
        )
        self.assertEqual(outcome.status, STATUS_OK)
        self.assertEqual([a.title for a in outcome.selected], [articles[1].title, articles[0].title])

    def test_unmatched_title_reports_without_import(self):
        articles = makeArticles(["基于地方志的空间数据整理"])
        outcome = resolveByTitlesFromList(["完全不存在的题目"], articles, confirm=True)
        self.assertEqual(outcome.status, STATUS_NEEDS_CONFIRM)
        self.assertEqual(outcome.selected, [])
        self.assertTrue(outcome.matchReport)

    def test_spreadsheet_missing_file_is_invalid(self):
        outcome = resolveBySpreadsheet("no-such-file.xlsx", makeArticles(["甲"]), {})
        self.assertEqual(outcome.status, STATUS_INVALID)

    def test_skip_all_marks_state_and_presented(self):
        articles = makeArticles(["甲", "乙"])
        with tempDataDir() as dataDir:
            state = stateManager({"stateFile": "./data/state.json"})
            outcome = resolveSkipAll(articles, state)
            self.assertEqual(outcome.status, STATUS_SKIP_ALL)
            self.assertEqual(outcome.skippedCount, 2)
            for article in articles:
                self.assertTrue(state.isArticleProcessed(article.journal, article.articleKey()))
                self.assertEqual(article.status, STATUS_PRESENTED)
            # 全部处理完毕后，该期次应被标记为已处理
            self.assertTrue(state.isIssueProcessed("数字人文研究", articles[0].issueInfo()))
            self.assertTrue((dataDir / "data" / "state.json").exists())


class ServiceDataTests(unittest.TestCase):
    def test_save_and_load_pending_round_trip(self):
        articles = makeArticles(["甲", "乙"])
        with tempDataDir() as dataDir:
            backups = savePending("# 清单", articles, captureType="issue")
            self.assertEqual(backups, [])
            self.assertTrue((dataDir / "data" / "pending.json").exists())

            markdown, loaded = loadPending()
            self.assertEqual(markdown, "# 清单")
            self.assertEqual([a.title for a in loaded], ["甲", "乙"])
            self.assertEqual([a._globalIndex for a in loaded], [1, 2])

    def test_second_capture_backs_up_previous_manifest(self):
        with tempDataDir() as dataDir:
            self.assertEqual(savePending("# 第一版", makeArticles(["甲"])), [])
            # 只有显式要求备份时才复制旧清单（cmdCapture 走的就是这条路）
            backups = savePending("# 第二版", makeArticles(["乙"]), backup=True)
            self.assertEqual(len(backups), 2)  # pending.json + review.md
            backupDir = (dataDir / "data" / "backups").resolve()
            for backup in backups:
                self.assertTrue(backup.exists())
                self.assertEqual(backup.parent.resolve(), backupDir)

    def test_capture_status_marks_review_stale_on_failure(self):
        with tempDataDir():
            saveCaptureStatus("failed", "没抓到", [])
            status = loadCaptureStatus()
            self.assertEqual(status["status"], "failed")
            self.assertTrue(status["reviewIsStale"])

            saveCaptureStatus("success", "抓到 3 篇", [])
            self.assertFalse(loadCaptureStatus()["reviewIsStale"])

    def test_write_text_artifact_reports_error_without_raising(self):
        with tempDataDir() as dataDir:
            target = dataDir / "data" / "report.md"
            self.assertIsNone(writeTextArtifact(target, "内容"))
            self.assertEqual(target.read_text(encoding="utf-8"), "内容")
            # 把目录本身当文件路径写入 → 应返回错误说明而不是抛异常
            self.assertIsNotNone(writeTextArtifact(dataDir / "data", "内容"))

    def test_preview_articles_is_read_only(self):
        articles = makeArticles(["甲"])
        rows = previewArticles(articles)
        self.assertEqual(rows[0]["position"], 1)
        self.assertEqual(rows[0]["index"], 1)
        self.assertEqual(rows[0]["title"], "甲")
        self.assertEqual(articles[0].status, "new")

    def test_pending_payload_shape_unchanged(self):
        """数据格式红线：pending.json 的字段名与层级不得改动。"""
        with tempDataDir() as dataDir:
            savePending("# 清单", makeArticles(["甲"]), note="备注", captureType="channel")
            payload = json.loads((dataDir / "data" / "pending.json").read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(payload.keys()),
                ["articles", "captureType", "capturedAt", "markdown", "note"],
            )
            self.assertEqual(payload["captureType"], "channel")
            self.assertEqual(payload["note"], "备注")
            self.assertEqual(payload["articles"][0]["_globalIndex"], 1)
            self.assertIn("title", payload["articles"][0])


class BasketRobustnessTests(unittest.TestCase):
    """筛选篮文件可能被人手改坏；loadBasket 必须降级为空/陈旧，绝不抛异常。"""

    def _basketPath(self, dataDir):
        path = dataDir / "data" / "basket.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_dirty_indexes_are_skipped_not_fatal(self):
        articles = makeArticles(["甲", "乙", "丙"])
        with tempDataDir() as dataDir:
            path = self._basketPath(dataDir)
            path.write_text(json.dumps({
                "pendingFingerprint": pendingFingerprint(articles),
                "selectedIndexes": [1, "abc", None, 2, "3", 999, 1],
            }), encoding="utf-8")
            state = loadBasket(path, articles)
            self.assertFalse(state.stale)
            self.assertEqual(state.indexes, [1, 2, 3])

    def test_corrupt_json_yields_stale_empty_basket(self):
        articles = makeArticles(["甲"])
        with tempDataDir() as dataDir:
            path = self._basketPath(dataDir)
            path.write_text("{ not json", encoding="utf-8")
            state = loadBasket(path, articles)
            self.assertTrue(state.stale)
            self.assertEqual(state.indexes, [])

    def test_non_dict_top_level_yields_stale_empty_basket(self):
        articles = makeArticles(["甲"])
        with tempDataDir() as dataDir:
            path = self._basketPath(dataDir)
            path.write_text("[1, 2, 3]", encoding="utf-8")
            state = loadBasket(path, articles)
            self.assertTrue(state.stale)
            self.assertEqual(state.indexes, [])


if __name__ == "__main__":
    unittest.main()
