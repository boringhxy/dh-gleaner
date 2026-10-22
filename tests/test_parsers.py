"""离线解析器烟雾测试 —— 用样例 HTML 断言字段抽取，不发任何网络请求。"""

from __future__ import annotations

import unittest

from dhgleaner.parsers.cnki_cbpt import CnkiCbptParser
from dhgleaner.parsers.journy3 import Journy3Parser
from dhgleaner.textutil import normalizeDate

try:
    from .samples import HTTP_CFG, SAMPLE_CNKI, SAMPLE_JOURNY3
except ImportError:  # 直接以脚本方式运行时
    from samples import HTTP_CFG, SAMPLE_CNKI, SAMPLE_JOURNY3


class Journy3ParserTests(unittest.TestCase):
    def testIssueAndArticleFields(self):
        parser = Journy3Parser("数字人文研究", HTTP_CFG)
        issue, articles = parser.parseCurrentIssue(SAMPLE_JOURNY3)

        self.assertEqual((issue.year, issue.volume, issue.issue), (2026, 6, 2))
        self.assertEqual(issue.publishDate, "2026-06-28")
        self.assertEqual(len(articles), 1)

        article = articles[0]
        self.assertEqual(article.articleUrl, "http://dhr.ruc.edu.cn/CN/Y2026/V6/I2/3")
        self.assertTrue(article.pdfUrl.endswith("id=172"))
        self.assertEqual(article.abstract, "摘要文本")


class CnkiCbptParserTests(unittest.TestCase):
    def testIssueAndArticleFields(self):
        parser = CnkiCbptParser("数字人文", HTTP_CFG)
        issue, articles = parser.parseCurrentIssue(SAMPLE_CNKI)

        self.assertEqual((issue.year, issue.issue), (2025, 4))
        self.assertIsNone(issue.volume)
        self.assertEqual(len(articles), 1)

        article = articles[0]
        self.assertEqual(
            article.articleUrl,
            "https://szrw.cbpt.cnki.net/WKC/WebPublication/paperDigest.aspx?paperID=uuid-123",
        )
        self.assertTrue(article.pdfUrl.endswith("fn=SZRW202504001"))
        self.assertEqual(article.authors, ["周墨钦", "王宏苏"])


class Journy3BaseUrlTests(unittest.TestCase):
    """站点地址来自配置，不是类里的常量 —— 否则换域名/转 https 只能改代码。"""

    def testConfiguredBaseUrlIsUsedForLinks(self):
        parser = Journy3Parser("镜像刊", HTTP_CFG, baseUrl="https://dhr.example.org/")
        issue, articles = parser.parseCurrentIssue(SAMPLE_JOURNY3)

        self.assertTrue(issue.year)
        self.assertEqual(articles[0].articleUrl, "https://dhr.example.org/CN/Y2026/V6/I2/3")
        self.assertTrue(articles[0].pdfUrl.startswith("https://dhr.example.org/CN/article/"))

    def testDefaultKeepsShippedSite(self):
        parser = Journy3Parser("数字人文研究", HTTP_CFG)
        _, articles = parser.parseCurrentIssue(SAMPLE_JOURNY3)

        self.assertTrue(articles[0].articleUrl.startswith("http://dhr.ruc.edu.cn"))


class PublishDateTests(unittest.TestCase):
    def testNormalize(self):
        cases = {
            "2026-06-28": "2026-06-28",
            "2026-6-2": "2026-06-02",
            "2026/6/28": "2026-06-28",
            "2026.06.28": "2026-06-28",
            "2026-06": "2026-06",
            "2026": "2026",
            " 2026-06-28 ": "2026-06-28",
            # 认不出来就留空：zotero_client 会让 date 回退成纯年份
            "--": "",
            "": "",
            "2026-13-01": "",
            "2026-06-40": "",
            "2026-06-28-abc": "",
            "forthcoming": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalizeDate(raw), expected)

    def testGarbledDateFromPageBecomesEmpty(self):
        html = SAMPLE_JOURNY3.replace("刊出日期：2026-06-28", "刊出日期：--")
        parser = Journy3Parser("数字人文研究", HTTP_CFG)
        issue, _ = parser.parseCurrentIssue(html)

        self.assertEqual(issue.publishDate, "")
        self.assertEqual(issue.year, 2026)

    def testUnpaddedDateFromPageIsPadded(self):
        html = SAMPLE_JOURNY3.replace("刊出日期：2026-06-28", "刊出日期：2026-6-2")
        parser = Journy3Parser("数字人文研究", HTTP_CFG)
        issue, _ = parser.parseCurrentIssue(html)

        self.assertEqual(issue.publishDate, "2026-06-02")


if __name__ == "__main__":
    unittest.main()
