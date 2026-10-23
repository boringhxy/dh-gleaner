"""state.json 原子写与损坏隔离用例。

覆盖三条被修复的行为：
1. 损坏的 state.json 不会被静默清空——旧文件另存为 `.corrupt-*` 备份；
2. 正常写入落盘后是合法 JSON；
3. `batch()` 把多次标记合并成一次写入，结果与逐次写入一致。
"""

from __future__ import annotations

import glob
import json
import os
import tempfile
import unittest
from pathlib import Path

from dhgleaner.models import Article
from dhgleaner.state import StateManager


def _article(title: str, url: str) -> Article:
    return Article(
        journal="数字人文研究",
        year=2026,
        volume=6,
        issue=2,
        title=title,
        articleUrl=url,
    )


class StateAtomicityTests(unittest.TestCase):
    def testCorruptStateIsBackedUpNotSilentlyDropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            statePath.write_text("{ this is not valid json", encoding="utf-8")

            state = StateManager(str(statePath))

            self.assertEqual(state.state["journals"], {})
            backups = glob.glob(str(statePath) + ".corrupt-*")
            self.assertEqual(len(backups), 1, "损坏文件应被另存为 .corrupt-* 备份")
            with open(backups[0], "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "{ this is not valid json")

    def testNonDictTopLevelIsQuarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            statePath.write_text("[1, 2, 3]", encoding="utf-8")

            state = StateManager(str(statePath))

            self.assertEqual(state.state["journals"], {})
            self.assertEqual(len(glob.glob(str(statePath) + ".corrupt-*")), 1)

    def testHandPatchedJournalEntryMissingFieldsIsBackfilled(self):
        """手工修复 state.json 后缺 processedArticles 不能让导入中途崩。

        _quarantineCorrupt 明确告诉用户「如需保留历史请从备份手工修复」，而人修出来的
        条目常常只留着 lastIssue 这类看得见的字段。读路径容忍缺失，写路径却直接索引，
        KeyError 会落在导入循环中间——那时前几篇已经写进 Zotero，进度和实际入库内容
        就对不上了。
        """
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            statePath.write_text(
                json.dumps({"journals": {"数字人文研究": {"lastIssue": None, "lastCheckAt": None}}}, ensure_ascii=False),
                encoding="utf-8",
            )

            state = StateManager(str(statePath))
            article = _article("甲", "http://example.com/a")

            self.assertFalse(state.isArticleProcessed(article.journal, article.articleKey()))
            state.markArticleProcessed(article.journal, article.articleKey(), title=article.title)
            self.assertTrue(state.isArticleProcessed(article.journal, article.articleKey()))

            # 整条缺失 / 值类型不对（手改成字符串）同样不该炸
            statePath.write_text(json.dumps({"journals": {"某刊": "手滑写成了字符串"}}, ensure_ascii=False), encoding="utf-8")
            state = StateManager(str(statePath))
            state.markArticleProcessed("某刊", "k1")
            self.assertTrue(state.isArticleProcessed("某刊", "k1"))

    def testSaveWritesValidJsonAndLeavesNoTempFile(self):
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            state = StateManager(str(statePath))

            article = _article("A", "u:a")
            state.markArticleProcessed(article.journal, article.articleKey(), title=article.title)

            data = json.loads(statePath.read_text(encoding="utf-8"))
            self.assertIn("u:a", data["journals"]["数字人文研究"]["processedArticles"])
            leftovers = [p for p in os.listdir(tmp) if p.startswith(".state-") and p.endswith(".tmp")]
            self.assertEqual(leftovers, [], "原子写不应留下临时文件")

    def testBatchProducesSameResultAsSequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            state = StateManager(str(statePath))

            articles = [_article(t, f"u:{t}") for t in ("A", "B", "C")]
            with state.batch():
                for article in articles:
                    state.markArticleProcessed(
                        article.journal, article.articleKey(), title=article.title, status="skipped"
                    )

            data = json.loads(statePath.read_text(encoding="utf-8"))
            processed = data["journals"]["数字人文研究"]["processedArticles"]
            self.assertEqual(sorted(processed), ["u:A", "u:B", "u:C"])

    def testBatchDefersWriteUntilExit(self):
        with tempfile.TemporaryDirectory() as tmp:
            statePath = Path(tmp) / "state.json"
            state = StateManager(str(statePath))
            article = _article("A", "u:a")

            with state.batch():
                state.markArticleProcessed(article.journal, article.articleKey(), title=article.title)
                self.assertFalse(statePath.exists(), "batch 期间不应落盘")
            self.assertTrue(statePath.exists(), "batch 退出后应落盘一次")


if __name__ == "__main__":
    unittest.main()
