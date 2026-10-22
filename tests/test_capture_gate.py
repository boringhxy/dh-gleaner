"""批量抓取的质量闸门与落盘保护。

守的是项目最核心的两条承诺：
1. 质量判定必须逐刊进行 —— 聚合后的文章数会掩盖单刊失败；
2. 判定不为 success 时绝不覆盖上一次的 pending.json。

这两条过去都没有测试：把 `_finishCapture` 的 `quality == "success"` 改成 `!=`，
整个测试套件依然全绿。
"""

from __future__ import annotations

import json
import unittest

try:
    from .helpers import pendingPayload, tempDataDir, writePending
except ImportError:  # 直接以脚本方式运行时
    from helpers import pendingPayload, tempDataDir, writePending
from dhgleaner.capture import (
    KIND_BLOCKED,
    KIND_FAILED,
    CaptureFailure,
    assessBatchQuality,
    assessCaptureQuality,
)
from dhgleaner.models import Article, IssueInfo
from dhgleaner.parsers.generic_html import GenericHtmlParser
from dhgleaner.paths import getPaths
from dhgleaner.service import CaptureOutcome, _finishCapture
from dhgleaner.textutil import isNavigationTitle


def makeArticle(journal: str, title: str, index: int) -> Article:
    return Article(
        journal=journal,
        year=2026,
        volume=6,
        issue=2,
        title=title,
        articleUrl=f"https://example.org/{journal}/{index}",
    )


def goodIssue() -> IssueInfo:
    return IssueInfo(year=2026, volume=6, issue=2)


def cleanArticles(journal: str, count: int) -> list[Article]:
    return [makeArticle(journal, f"{journal}正经论文标题{i}", i) for i in range(count)]


class BatchQualityTests(unittest.TestCase):
    def testTwelveJournalsFailingDoesNotLookLikeSuccess(self):
        """回归：12 刊失败 + 1 刊成功，聚合判定过去会给出 success。"""
        results = [("坏刊%d" % i, None, []) for i in range(12)]
        results.append(("好刊", goodIssue(), cleanArticles("好刊", 6)))
        failures = [
            CaptureFailure("坏刊%d" % i, "fetch", KIND_FAILED, "抓取失败") for i in range(12)
        ]

        quality, reason = assessBatchQuality(results, failures, captureType="issue")

        self.assertEqual(quality, "suspect")
        self.assertIn("12/13", reason)
        self.assertIn("坏刊0", reason)

    def testAllJournalsCleanIsSuccess(self):
        results = [
            ("刊A", goodIssue(), cleanArticles("刊A", 5)),
            ("刊B", goodIssue(), cleanArticles("刊B", 7)),
        ]
        quality, reason = assessBatchQuality(results, [], captureType="issue")
        self.assertEqual(quality, "success")
        self.assertEqual(reason, "")

    def testEveryJournalFailingIsFailedNotSuspect(self):
        results = [("刊A", None, []), ("刊B", None, [])]
        failures = [CaptureFailure("刊A", "fetch", KIND_BLOCKED, "412"), CaptureFailure("刊B", "fetch", KIND_FAILED, "超时")]
        quality, reason = assessBatchQuality(results, failures, captureType="issue")
        self.assertEqual(quality, "failed")
        self.assertIn("412", reason)

    def testLegitEmptyJournalDoesNotDragDownTheBatch(self):
        """dedupe 命中已处理期次 / dhOnly 筛完无命中 = 合法的空，不记 failure。"""
        results = [
            ("刊A", goodIssue(), []),
            ("刊B", goodIssue(), cleanArticles("刊B", 5)),
        ]
        quality, _ = assessBatchQuality(results, [], captureType="issue")
        self.assertEqual(quality, "success")

    def testAllLegitEmptyIsFailedWithExplanation(self):
        results = [("刊A", goodIssue(), []), ("刊B", goodIssue(), [])]
        quality, reason = assessBatchQuality(results, [], captureType="issue")
        self.assertEqual(quality, "failed")
        self.assertIn("已处理过", reason)

    def testGarbageTitlesInOneJournalAreCaught(self):
        """逐刊判定要能揪出单刊的垃圾标题，而不是被其他刊的干净文章稀释。"""
        junk = [makeArticle("坏刊", "首页", i) for i in range(4)]
        results = [
            ("好刊", goodIssue(), cleanArticles("好刊", 40)),
            ("坏刊", goodIssue(), junk),
        ]
        quality, reason = assessBatchQuality(results, [], captureType="issue")
        self.assertEqual(quality, "suspect")
        self.assertIn("坏刊", reason)

    def testEmptyResultsIsFailed(self):
        quality, reason = assessBatchQuality([], [], captureType="issue")
        self.assertEqual(quality, "failed")
        self.assertIn("没有任何期刊", reason)

    def testBlockedAndFailedAreDistinguishable(self):
        blocked = CaptureFailure("甲", "fetch", KIND_BLOCKED, "站点拒绝自动化访问")
        retryable = CaptureFailure("乙", "fetch", KIND_FAILED, "连接超时")
        self.assertIn("拒绝", blocked.describe())
        self.assertNotEqual(blocked.kind, retryable.kind)
        self.assertEqual(blocked.toDict()["stage"], "fetch")


class FinishCaptureGateTests(unittest.TestCase):
    """落盘闸门：只有 success 才允许覆盖 pending.json。"""

    def makeOutcome(self, quality: str, articles: list[Article], reason: str = "") -> CaptureOutcome:
        return CaptureOutcome(
            journal="测试刊",
            issue="2026年 第6卷 第2期",
            markdown="# 测试清单",
            articles=articles,
            quality=quality,
            reason=reason,
            status=quality,
            collected=[("测试刊", goodIssue(), articles)],
        )

    def testSuccessWritesPending(self):
        with tempDataDir():
            outcome = self.makeOutcome("success", cleanArticles("测试刊", 5))
            result = _finishCapture(outcome, captureType="issue", note="", dryRun=False)

            self.assertTrue(result.wrotePending)
            saved = json.loads(getPaths().pending.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["articles"]), 5)

    def testSuspectDoesNotOverwriteExistingPending(self):
        with tempDataDir():
            target = writePending(pendingPayload([a.toDict() for a in cleanArticles("旧刊", 9)]))
            before = target.read_text(encoding="utf-8")

            outcome = self.makeOutcome("suspect", cleanArticles("测试刊", 5), reason="疑似误抓")
            result = _finishCapture(outcome, captureType="issue", note="", dryRun=False)

            self.assertFalse(result.wrotePending)
            self.assertEqual(result.status, "suspect")
            self.assertEqual(target.read_text(encoding="utf-8"), before, "suspect 不得覆盖旧清单")

    def testFailedDoesNotOverwriteExistingPending(self):
        with tempDataDir():
            target = writePending(pendingPayload([a.toDict() for a in cleanArticles("旧刊", 9)]))
            before = target.read_text(encoding="utf-8")

            outcome = self.makeOutcome("failed", [], reason="全部抓取失败")
            result = _finishCapture(outcome, captureType="issue", note="", dryRun=False)

            self.assertFalse(result.wrotePending)
            self.assertEqual(result.status, "failed")
            self.assertEqual(target.read_text(encoding="utf-8"), before)

    def testDryRunNeverWrites(self):
        with tempDataDir():
            outcome = self.makeOutcome("success", cleanArticles("测试刊", 5))
            result = _finishCapture(outcome, captureType="issue", note="", dryRun=True)

            self.assertFalse(result.wrotePending)
            self.assertFalse(getPaths().pending.exists())

    def testDegradedBatchRecordsFailuresInStatusFile(self):
        """失败原因要落进 last_capture_status.json —— 报障时要用户附的就是这个文件。"""
        with tempDataDir():
            outcome = self.makeOutcome("suspect", cleanArticles("测试刊", 5), reason="1/2 本刊异常")
            outcome.failures = [CaptureFailure("坏刊", "fetch", KIND_BLOCKED, "HTTP 412")]
            outcome.collected = [("测试刊", goodIssue(), outcome.articles), ("坏刊", None, [])]

            _finishCapture(outcome, captureType="issue", note="", dryRun=False)

            status = json.loads(getPaths().captureStatus.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "suspect")
            self.assertTrue(status["reviewIsStale"])
            self.assertEqual(len(status["failures"]), 1)
            self.assertEqual(status["failures"][0]["kind"], "blocked")
            self.assertEqual(status["failures"][0]["journal"], "坏刊")

    def testBlockedJournalsAreSurfacedSeparately(self):
        with tempDataDir():
            outcome = self.makeOutcome("suspect", cleanArticles("测试刊", 3))
            outcome.failures = [
                CaptureFailure("甲", "fetch", KIND_BLOCKED, "412"),
                CaptureFailure("乙", "fetch", KIND_FAILED, "超时"),
            ]
            self.assertEqual(outcome.blockedJournals, ["甲"])


class SharedNavigationBlacklistTests(unittest.TestCase):
    """两份导航词黑名单合成一处之后，两条链路必须认同一批词。

    过去 `capture` 的质量闸门和 `generic_html` 各维护一份词表：闸门那份没有
    「过刊浏览 / 在线投稿 / 关于我们 / 广告合作」，所以整页抓成导航时
    照样能报 success 并覆盖旧清单。
    """

    DRIFTED_WORDS = ["过刊浏览", "在线投稿", "关于我们", "广告合作"]

    def testGateKnowsTheWordsGenericHtmlAlreadyKnew(self):
        for word in self.DRIFTED_WORDS:
            self.assertTrue(isNavigationTitle(word), word)

    def testNavigationOnlyBatchIsSuspect(self):
        articles = [makeArticle("测试刊", word, i) for i, word in enumerate(self.DRIFTED_WORDS)]
        status, reason = assessCaptureQuality(goodIssue(), articles, captureType="issue")
        self.assertEqual(status, "suspect")
        self.assertIn("导航", reason)

    def testGenericHtmlStillDropsTitlesContainingThoseWords(self):
        html = '''<html><body><main class="content">
        <a href="https://dhcn.cn/a">数字人文资源的过刊浏览与再组织</a>
        <a href="https://dhcn.cn/b">数字人文视角下的文献整合研究</a>
        </main></body></html>'''
        parser = GenericHtmlParser(
            "测试刊",
            {"userAgent": "Mozilla/5.0"},
            baseUrl="https://dhcn.cn",
            options={"containerSelectors": ["main.content"], "allowedDomains": ["dhcn.cn"]},
        )
        _, arts = parser.parseCurrentIssue(html)
        self.assertEqual([a.title for a in arts], ["数字人文视角下的文献整合研究"])

    def testLatinNavigationWordsDoNotSwallowARealTitle(self):
        """拉丁词只做整条相等，否则标题里带 Journal / More 的论文会被误判成导航。"""
        self.assertFalse(isNavigationTitle("Journal of Digital Humanities 的引文分析"))
        self.assertFalse(isNavigationTitle("面向数字人文资源的 MORE 模型比较"))
        self.assertTrue(isNavigationTitle("Journal"))
        self.assertTrue(isNavigationTitle("Read  More"))


class GarbledTextGateTests(unittest.TestCase):
    """解码失败的替换符必须拦住落盘。

    站点声明错编码、或 requests 猜错 apparent_encoding 时，整页中文会变成成片
    U+FFFD。这类清单看着「有文章、标题不重复」，过去能直接判 success 覆盖旧清单。
    """

    def garbledArticle(self, journal: str, where: str) -> Article:
        article = makeArticle(journal, f"{journal}数字人文研究标题", 1)
        if where == "title":
            article.title = f"{journal}数字人文\ufffd\ufffd究标题"
        else:
            article.abstract = "数字人文\ufffd\ufffd\ufffd的\ufffd献整理方法"
        return article

    def testGarbledTitleIsSuspect(self):
        status, reason = assessCaptureQuality(goodIssue(), [self.garbledArticle("测试刊", "title")])
        self.assertEqual(status, "suspect")
        self.assertIn("U+FFFD", reason)

    def testGarbledAbstractIsSuspect(self):
        status, _ = assessCaptureQuality(goodIssue(), [self.garbledArticle("测试刊", "abstract")])
        self.assertEqual(status, "suspect")

    def testCleanBatchIsNotFlagged(self):
        articles = [makeArticle("测试刊", f"数字人文研究标题{i}", i) for i in range(5)]
        for article in articles:
            article.abstract = "基于图谱的文献计量分析方法"
        status, reason = assessCaptureQuality(goodIssue(), articles)
        self.assertEqual(status, "success", reason)

    def testOneGarbledJournalDragsTheBatchToSuspect(self):
        results = [
            ("好刊", goodIssue(), cleanArticles("好刊", 20)),
            ("乱码刊", goodIssue(), [self.garbledArticle("乱码刊", "title")]),
        ]
        quality, reason = assessBatchQuality(results, [], captureType="issue")
        self.assertEqual(quality, "suspect")
        self.assertIn("乱码刊", reason)


if __name__ == "__main__":
    unittest.main()
