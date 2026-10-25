"""发现层 — 「这本刊现在最新的已知期次是哪一期」。

发现层是这次「《数字人文》永远抓不到最新一期」的根治点，所以这里守的全是
实测踩过来的坑，而不是通用解析：

1. magtech 的 `volumn_N` 是 CMS 内部 id，跨刊跨年都不单调（实测情报科学
   id 1275=第2期、id 1273=第5期）→ 期次只能按页面文本取 (年,期) 最大值；
2. 同一张过刊页里「No.1–No.8」与「No.413–No.416」（总期号）并存 → 大于 12 的必须忽略；
3. JournalX 不存在的档也返回 200 且回显「2026年第N期目录」→ 判据只能是正文链接数；
   扫描起点要按该刊的年发文量算，双月刊从第12档往下扫会把最新的第4期整段跨过去；
4. 微信公众号目录推文是唯一最早的公告，但站外不可列举 → 没人贴链接时必须是「等人」，
   不能伪装成「抓不到」或「没有新刊」；
5. 没有标期次的更新（如 WordPress 首页最新推文）不能当「最新一期」。
"""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from dhgleaner import discovery
from dhgleaner.paths import defaultConfigPath
from dhgleaner.state import StateManager

TODAY = date(2026, 10, 24)
UA = "test-agent"


def archiveHtml() -> str:
    """magtech volumn_N 皮肤：id 大的那一期反而更小（照抄情报科学的实测形状）。"""
    return """
    <html><body><div class="oldVolumn">
      <h3>2025年 第43卷</h3>
      <ul class="lunwen">
        <li><a href="../volumn/volumn_1273.shtml">第5期</a></li>
        <li><a href="../volumn/volumn_1275.shtml">第2期</a></li>
      </ul>
      <h3>2026年 第44卷</h3>
      <ul class="lunwen">
        <li><a href="../volumn/volumn_1301.shtml">第5期</a></li>
        <li><a href="../volumn/volumn_1305.shtml">第2期</a></li>
      </ul>
    </div></body></html>
    """


def mixedNumberingHtml() -> str:
    """年度块里同时出现年度期号与总期号（图书馆杂志 2026 年的真实形状）。"""
    return """
    <html><body>
      <h3>2026年 第45卷</h3>
      <table>
        <tr><td><a href="../volumn/volumn_9.shtml">No.8</a></td></tr>
        <tr><td><a href="../volumn/volumn_10.shtml">No.416</a></td></tr>
      </table>
    </body></html>
    """


def journalxHtml(populated: bool) -> str:
    """JournalX 列表页；空档同样回显「2026年第N期目录」。"""
    rows = ""
    if populated:
        rows = (
            '<tr><td><a href="view_abstract.aspx?file_no=20260401">一篇正经论文标题</a></td></tr>'
            '<tr><td><a href="view_abstract.aspx?file_no=20260402">另一篇正经论文标题</a></td></tr>'
        )
    return f"""
    <html><body>2026年第5期目录 浏览其它刊期: 2026年 2025年
      <table>{rows}</table>
    </body></html>
    """


def wechatHtml(title: str, body: str = "本辑收录论文十篇") -> str:
    return f"""
    <html><head><meta property="og:title" content="{title}"></head>
    <body><div id="js_content">{body}</div></body></html>
    """


def cnkiHtml(text: str) -> str:
    return f"<html><body><div class='toc'>{text}</div></body></html>"


def journalWithSources(name: str, sources: list, issuesPerYear: int = 6) -> dict:
    return {
        "name": name,
        "url": "https://example.org/",
        "parser": "magtech",
        "discovery": {"issuesPerYear": issuesPerYear, "sources": sources},
    }


def source(specId: str, kind: str, **overrides) -> dict:
    spec = {"id": specId, "kind": kind, "tier": 2, "official": True, "fetch": "harvest"}
    spec.update(overrides)
    return spec


def runJournal(journalCfg: dict, state=None, today: date = TODAY) -> discovery.JournalDiscovery:
    return discovery.discoverJournal(journalCfg, {"userAgent": UA}, state=state, today=today, record=False)


class ArchiveSourceTests(unittest.TestCase):
    def testLatestIssueComesFromTextNotVolumnId(self):
        """volumn_1305 是第2期、volumn_1301 才是第5期：按 id 取大会得到旧期。"""
        with mock.patch.object(discovery, "fetchHtml", return_value=archiveHtml()):
            item = runJournal(
                journalWithSources("情报科学", [source("archive", "archive_volumn_links", url="https://x/CN/article/showOldVolumn.do")])
            )
        self.assertEqual((item.frontier.year, item.frontier.issue, item.frontier.volume), (2026, 5, 44))
        self.assertTrue(item.frontier.url.endswith("volumn_1301.shtml"), item.frontier.url)

    def testTotalIssueNumberIsNotUsedAsIssue(self):
        with mock.patch.object(discovery, "fetchHtml", return_value=mixedNumberingHtml()):
            item = runJournal(
                journalWithSources("图书馆杂志", [source("archive", "archive_volumn_links", url="https://x/CN/article/showOldVolumn.do")])
            )
        self.assertEqual((item.frontier.year, item.frontier.issue), (2026, 8))
        self.assertLessEqual(item.frontier.issue, discovery.MAX_ISSUE_PER_YEAR)

    def testVolumeAloneIsNotMistakenForIssue(self):
        """「第6卷」里没有年度期号，绝不能把卷号读成第6期。"""
        self.assertEqual(discovery._issueFrom(["2026年 第6卷"]), 0)
        self.assertEqual(discovery._issueFrom(["第6卷 第1期"]), 1)


class JournalxScanWindowTests(unittest.TestCase):
    def testEmptyQuarterEchoingHeaderIsRejected(self):
        calls = []

        def fake(url, ua="", **kwargs):
            calls.append(url)
            return journalxHtml(populated="quarter_id=4" in url)

        journalCfg = journalWithSources(
            "中国图书馆学报",
            [source("quarter_scan", "journalx_quarter_scan", url="https://x/ch/reader/", maxScanSteps=4)],
        )
        with mock.patch.object(discovery, "fetchHtml", side_effect=fake):
            item = runJournal(journalCfg)
        self.assertEqual((item.frontier.year, item.frontier.issue), (2026, 4))
        self.assertTrue(calls[0].endswith("quarter_id=5"), calls)
        self.assertEqual(len(calls), 2)

    def testBimonthlyDoesNotStartAtTwelve(self):
        """起点按 issuesPerYear 折算：10 月的双月刊从第5档开扫，而不是第12档。"""
        self.assertEqual(
            discovery._expectedQuarter(date(2026, 10, 24), issuesPerYear=6, maxQuarter=12), 5
        )
        self.assertEqual(
            discovery._expectedQuarter(date(2026, 10, 24), issuesPerYear=12, maxQuarter=12), 10
        )


class ManualSourceTests(unittest.TestCase):
    def testWechatWithoutRecordedUrlWaitsForHuman(self):
        journalCfg = journalWithSources(
            "数字人文",
            [
                source("wechat_toc", "wechat_toc_issue", tier=1, official=False, fetch="manual", url="", requiredPageText=["数字人文"]),
                source("cbpt", "cnki_cbpt_current", url="https://x/index.aspx"),
            ],
            issuesPerYear=4,
        )
        with mock.patch.object(discovery, "fetchHtml", return_value=cnkiHtml("2025年04期")):
            item = runJournal(journalCfg)
        wechat = next(s for s in item.sources if s.sourceId == "wechat_toc")
        self.assertEqual(wechat.status, "manual")
        self.assertIn("--record-url", wechat.detail)
        self.assertEqual(item.frontier.issue, 4)

    def testRecordedTocPushWinsAndOfficialLagIsMeasured(self):
        """实测的核心场景：公众号已公告 2026 年第3期，官网还停在 2025 年第4期。"""
        with TemporaryDirectory() as tmp:
            state = StateManager(str(Path(tmp) / "state.json"))
            state.recordManualIssueUrl("数字人文", "wechat_toc", "https://mp.weixin.qq.com/s/abc")
            journalCfg = journalWithSources(
                "数字人文",
                [
                    source("wechat_toc", "wechat_toc_issue", tier=1, official=False, fetch="manual", url="", requiredPageText=["数字人文"]),
                    source("cbpt", "cnki_cbpt_current", url="https://x/index.aspx"),
                ],
                issuesPerYear=4,
            )

            def fake(url, ua="", **kwargs):
                if "weixin" in url:
                    return wechatHtml("《数字人文》2026年第3期目录")
                return cnkiHtml("2025年04期")

            with mock.patch.object(discovery, "fetchHtml", side_effect=fake):
                item = runJournal(journalCfg, state=state)
        payload = item.toDict()
        self.assertEqual(payload["frontier"]["label"], "2026年第3期")
        self.assertEqual(payload["frontier"]["tier"], 1)
        self.assertEqual(payload["official"]["label"], "2025年第4期")
        cbpt = next(s for s in payload["sources"] if s["sourceId"] == "cbpt")
        self.assertEqual(cbpt["lagIssues"], 3)

    def testWrongWeChatPageDoesNotBecomeFrontier(self):
        journalCfg = journalWithSources(
            "数字人文",
            [source("wechat_toc", "wechat_toc_issue", tier=1, official=False, url="", requiredPageText=["数字人文"])],
        )
        with mock.patch.object(discovery, "fetchHtml", return_value="<html><body>登录</body></html>"):
            with TemporaryDirectory() as tmp:
                state = StateManager(str(Path(tmp) / "state.json"))
                state.recordManualIssueUrl("数字人文", "wechat_toc", "https://mp.weixin.qq.com/s/abc")
                item = runJournal(journalCfg, state=state)
        self.assertEqual(item.sources[0].status, "failed")
        self.assertIsNone(item.frontier)


class FrontierGuardTests(unittest.TestCase):
    def testUnnumberedPostIsNotAFrontier(self):
        """站点首页最新一篇没有标期次的推文，只能算「站上有今年内容」的信号。"""
        journalCfg = journalWithSources(
            "中国数字人文",
            [
                source("wp_categories", "wordpress_issue_categories", url="https://x/wp-json/wp/v2/categories"),
                source("wp_latest", "wordpress_latest_posts", tier=3, official=False, url="https://x/wp-json/wp/v2/posts"),
            ],
        )
        categories = [{"name": "2025年第4期", "link": "https://x/202504", "count": 11}]
        posts = [{"title": {"rendered": "某学术活动通知"}, "date": "2026-05-01T00:00:00", "link": "https://x/post"}]

        def fakeJson(url, ua="", **kwargs):
            return posts if "posts" in url else categories

        with mock.patch.object(discovery, "fetchJson", side_effect=fakeJson):
            item = runJournal(journalCfg)
        self.assertEqual(item.frontier.sourceId, "wp_categories")
        self.assertEqual(item.frontier.issue, 4)
        self.assertIsNone(item.sources[1].gapTo(item.frontier, item.issuesPerYear))


class NextActionTests(unittest.TestCase):
    def testChannelJournalSuggestsCaptureChannel(self):
        """图书馆杂志：期次能发现，但正文只能从栏目页拿。"""
        journalCfg = journalWithSources(
            "图书馆杂志",
            [
                source(
                    "archive",
                    "archive_volumn_links",
                    fetch="channel",
                    channel="数字人文",
                    url="https://x/showOldVolumn.do",
                )
            ],
        )
        html = mixedNumberingHtml()
        with mock.patch.object(discovery, "fetchHtml", return_value=html):
            item = runJournal(journalCfg)
        self.assertIn("capture-channel --journal 图书馆杂志 --channel 数字人文", item.nextAction)

    def testHarvestJournalSuggestsHarvestYear(self):
        journalCfg = journalWithSources(
            "情报科学",
            [source("archive", "archive_volumn_links", url="https://x/showOldVolumn.do")],
        )
        with mock.patch.object(discovery, "fetchHtml", return_value=archiveHtml()):
            item = runJournal(journalCfg)
        self.assertEqual(item.nextAction, "dhgleaner harvest --journal 情报科学 --year 2026")


class FreshnessWarningTests(unittest.TestCase):
    def testStaleCaptureWarnsWithoutChangingStatus(self):
        from dhgleaner.models import IssueInfo
        from dhgleaner.service import freshnessWarnings

        with TemporaryDirectory() as tmp:
            state = StateManager(str(Path(tmp) / "state.json"))
            state.recordLatestKnown("数字人文", {"year": 2026, "issue": 3, "label": "2026年第3期", "sourceId": "wechat_toc"})
            results = [("数字人文", IssueInfo(year=2025, issue=4), [])]
            warnings = freshnessWarnings(state, results)
            self.assertEqual(len(warnings), 1)
            self.assertIn("2026年第3期", warnings[0])
            self.assertIn("discover", warnings[0])
            same = freshnessWarnings(state, [("数字人文", IssueInfo(year=2026, issue=3), [])])
            self.assertEqual(same, [])
            unknown = freshnessWarnings(state, [("没记录过的刊", IssueInfo(year=2025, issue=4), [])])
            self.assertEqual(unknown, [])


class ConfigCoverageTests(unittest.TestCase):
    """配置里写错 kind/fetch 名时，发现层只会安静地报 failed；这里把它变成测试失败。"""

    def setUp(self):
        import json

        with open(defaultConfigPath(), "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

    def testEveryJournalHasDiscoverySources(self):
        missing = [j["name"] for j in self.cfg["journals"] if not (j.get("discovery") or {}).get("sources")]
        self.assertEqual(missing, [], f"这些刊还没有发现源配置: {missing}")

    def testEverySourceKindAndActionIsKnown(self):
        for journal in self.cfg["journals"]:
            for spec in (journal.get("discovery") or {}).get("sources") or []:
                identity = spec.get("id") or spec.get("kind")
                self.assertIn(spec.get("kind"), discovery.ENUMERATORS, f"{journal['name']}/{identity} kind 未知")
                self.assertIn(spec.get("fetch"), discovery.FETCH_ACTIONS, f"{journal['name']}/{identity} fetch 未知")
                if spec.get("kind") in ("archive_volumn_links", "cnki_cbpt_current", "journalx_quarter_scan",
                                         "wordpress_issue_categories", "wordpress_latest_posts"):
                    self.assertTrue(spec.get("url"), f"{journal['name']}/{identity} 缺 url")


if __name__ == "__main__":
    unittest.main()
