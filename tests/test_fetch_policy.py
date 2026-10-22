"""抓取节流策略：退避、Retry-After、分页封顶。

守的是「别给对方站点造成压力，也别因为一次误解析就发出上万个请求」：

1. 重试间隔指数增长，站点给了 ``Retry-After`` 就听站点的；
2. 401/403/412 一次都不重试；
3. 栏目分页数有硬上限，触顶时记为失败而不是静默少给清单；
4. 同一栏目的逐页抓取之间按 ``harvestDelay`` 限速。

这几条过去一个测试都没有：把退避改回固定间隔、或把分页上限删掉，套件依然全绿。
"""

from __future__ import annotations

import unittest
from unittest import mock

import dhgleaner.capture as capture_module
import dhgleaner.http_util as http_module
from dhgleaner.capture import captureChannel
from dhgleaner.http_util import MAX_RETRY_DELAY, FetchBlocked, FetchFailed, fetchHtml
from dhgleaner.parsers.magtech import MagtechParser
from dhgleaner.state import StateManager

try:
    from .helpers import tempDataDir
except ImportError:  # 直接以脚本方式运行时
    from helpers import tempDataDir

UA = "Mozilla/5.0"
CHANNEL_URL = "https://example.org/CN/article/showChannelArticle.do?id=60"
CHANNEL_HTML = """<html><body>
<span class="item-columnName">数字人文</span>
<li>共{pages}页</li>
</body></html>"""


class FakeResponse:
    def __init__(self, statusCode: int, headers=None, text: str = "<html>ok</html>"):
        self.status_code = statusCode
        self.headers = dict(headers or {})
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise http_module.requests.HTTPError(f"HTTP {self.status_code}", response=self)


def runFetch(responses, retryInterval=3, maxRetries=4):
    """按顺序回放假响应跑一遍 fetchHtml，返回 (结果或异常, 实际 sleep 的秒数)。"""
    queue = list(responses)
    sleeps: list[float] = []

    def fakeGet(url, **kwargs):
        return queue.pop(0)

    with mock.patch.object(http_module.requests, "get", fakeGet):
        with mock.patch.object(http_module.time, "sleep", sleeps.append):
            try:
                result = fetchHtml(
                    "https://example.org/",
                    UA,
                    retryInterval=retryInterval,
                    maxRetries=maxRetries,
                )
            except Exception as exc:  # noqa: BLE001 - 用例要断言异常类型
                result = exc
    return result, sleeps


class RetryBackoffTests(unittest.TestCase):
    def testRetriesBackOffExponentially(self):
        result, sleeps = runFetch([FakeResponse(500), FakeResponse(500), FakeResponse(200)])
        self.assertEqual(result, "<html>ok</html>")
        self.assertEqual(sleeps, [3, 6])

    def testRetryAfterHeaderBeatsOurOwnGuess(self):
        _, sleeps = runFetch([FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200)])
        self.assertEqual(sleeps, [7.0])

    def testUnparsableRetryAfterFallsBackToBackoff(self):
        _, sleeps = runFetch([FakeResponse(429, {"Retry-After": "soon"}), FakeResponse(200)])
        self.assertEqual(sleeps, [3])

    def testBackoffNeverExceedsTheCeiling(self):
        _, sleeps = runFetch(
            [FakeResponse(500), FakeResponse(500), FakeResponse(500), FakeResponse(200)],
            retryInterval=200,
        )
        self.assertEqual(sleeps, [200, MAX_RETRY_DELAY, MAX_RETRY_DELAY])

    def testBlockingStatusIsNotRetriedAtAll(self):
        sleeps: list[float] = []
        with mock.patch.object(http_module.requests, "get", return_value=FakeResponse(412)) as fakeGet:
            with mock.patch.object(http_module.time, "sleep", sleeps.append):
                with self.assertRaises(FetchBlocked):
                    fetchHtml("https://example.org/", UA, retryInterval=3, maxRetries=4)
        self.assertEqual(fakeGet.call_count, 1, "412 是明确拒绝，重试只是继续骚扰对方")
        self.assertEqual(sleeps, [])

    def testExhaustedRetriesRaiseFetchFailed(self):
        result, sleeps = runFetch([FakeResponse(500), FakeResponse(500)], maxRetries=2)
        self.assertIsInstance(result, FetchFailed)
        self.assertEqual(sleeps, [3])


class ChannelPaginationCapTests(unittest.TestCase):
    def discover(self, totalPages: int, **cfgOverrides):
        cfg = {"maxChannelPages": 5, **cfgOverrides}
        parser = MagtechParser("图书馆杂志", {"userAgent": UA}, journalCfg=cfg)
        return parser.discoverChannelPageUrls(CHANNEL_HTML.format(pages=totalPages), CHANNEL_URL)

    def testRunawayPageCountIsCappedNotFollowed(self):
        """「共 N 页」是正则从页面文本里抠的，抠错一位数就是几万个请求。"""
        self.assertEqual(len(self.discover(99999)), 5)

    def testNormalPageCountIsLeftAlone(self):
        self.assertEqual(len(self.discover(3)), 3)

    def testCapIsConfigurable(self):
        self.assertEqual(len(self.discover(99999, maxChannelPages=2)), 2)


class ChannelThrottleTests(unittest.TestCase):
    def capture(self, totalPages: int, **cfgOverrides):
        cfg = {
            "name": "图书馆杂志",
            "parser": "magtech",
            "channelSources": [{"channel": "数字人文", "url": CHANNEL_URL}],
            **cfgOverrides,
        }
        html = CHANNEL_HTML.format(pages=totalPages)
        sleeps: list[float] = []
        with tempDataDir() as dataDir:
            state = StateManager(str(dataDir / "state.json"))
            with mock.patch.object(capture_module, "fetchHtml", return_value=html):
                with mock.patch.object(capture_module.time, "sleep", sleeps.append):
                    issue, articles, failure = captureChannel(
                        cfg,
                        {"userAgent": UA, "harvestDelay": 0.6},
                        state,
                        "数字人文",
                    )
        return issue, articles, failure, sleeps

    def testPagesAreFetchedWithAPoliteGap(self):
        _, _, failure, sleeps = self.capture(3)
        self.assertEqual(sleeps, [0.6, 0.6], "同一主机的逐页请求之间必须限速")
        self.assertIsNone(failure)

    def testHittingThePageCapIsReportedNotSilent(self):
        _, _, failure, _ = self.capture(500, maxChannelPages=2)
        self.assertIsNotNone(failure, "触到分页封顶却报 success，等于静默少给一截清单")
        self.assertEqual(failure.kind, "failed")
        self.assertIn("maxChannelPages", failure.detail)

    def testNonMagtechParserIsRejectedBeforeAnyRequest(self):
        """栏目抓取只对 magtech 开放，README 与 docs/workflow.md 都写的是这句话。

        这一支必须在看站点之前就返回，否则给不支持的皮肤白耗一次请求。
        """
        cfg = {"name": "数字人文研究", "parser": "journy3", "url": "http://dhr.ruc.edu.cn"}
        with tempDataDir() as dataDir:
            with mock.patch.object(
                capture_module,
                "fetchHtml",
                side_effect=AssertionError("不该发出请求"),
            ):
                issue, articles, failure = captureChannel(
                    cfg, {"userAgent": UA}, StateManager(str(dataDir / "state.json")), "数字人文"
                )
        self.assertIsNone(issue)
        self.assertEqual(articles, [])
        self.assertEqual(failure.stage, "unsupported")
        self.assertIn("暂不支持 capture-channel", failure.detail)
