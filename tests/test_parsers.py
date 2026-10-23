"""离线解析器烟雾测试 —— 用样例 HTML 断言字段抽取，不发任何网络请求。"""

from __future__ import annotations

import unittest

from dhgleaner.parsers.cnki_cbpt import CnkiCbptParser
from dhgleaner.parsers.generic_html import GenericHtmlParser
from dhgleaner.parsers.journy3 import Journy3Parser
from dhgleaner.textutil import normalizeDate

try:
    from .samples import HTTP_CFG, SAMPLE_CNKI, SAMPLE_GENERIC, SAMPLE_GENERIC_DHCN, SAMPLE_JOURNY3
except ImportError:  # 直接以脚本方式运行时
    from samples import HTTP_CFG, SAMPLE_CNKI, SAMPLE_GENERIC, SAMPLE_GENERIC_DHCN, SAMPLE_JOURNY3


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


class GenericHtmlChromeTests(unittest.TestCase):
    """generic_html 抓 WordPress 式清单页：站点外壳不能进清单，栏目不能错位一格。"""

    options = {
        "allowedDomains": ["dhcn.cn", "mp.weixin.qq.com"],
        "containerSelectors": ["h2.entry-title"],
        "titleKeywords": ["数字人文", "人文", "数据", "历史", "文献"],
    }

    def _parse(self):
        parser = GenericHtmlParser(
            "中国数字人文", HTTP_CFG, baseUrl="https://www.dhcn.cn/category/dhjournal/202504",
            options=self.options,
        )
        return parser.parseCurrentIssue(SAMPLE_GENERIC_DHCN)

    def testIssueNumberFromPageTitle(self):
        """h1 写作「《数字人文》2025年第4期」——带「第」字的期号不能被读成 0。"""
        issue, _ = self._parse()

        self.assertEqual((issue.year, issue.issue), (2025, 4))

    def testOnlyRealItemsSurvive(self):
        _, articles = self._parse()

        self.assertEqual(
            [a.title for a in articles],
            [
                "迈向AI时代：数字人文基础设施的先锋之路 ——刘炜先生访谈录",
                "基于改进YOLOv8的刺绣动态检测与分类研究",
            ],
        )

    def testSectionIsNotThePreviousItemTitle(self):
        """每条自己的题名是 h2，前一个 h2 属于上一篇文章 —— 不能当成栏目。"""
        _, articles = self._parse()

        self.assertEqual([a.section for a in articles], ["", ""])

    def testKeywordFilterIsSkippedForTrustedContainers(self):
        """指定了 containerSelectors 就人工认定容器内全是条目，题名不含关键词也要留。"""
        _, articles = self._parse()

        self.assertTrue(all(a.articleUrl.startswith("https://mp.weixin.qq.com/") for a in articles))

    def testChromeFilterAppliesWithoutContainerSelectors(self):
        """没配 containerSelectors 时（如 Airiti 页），外壳链接仍被结构过滤挡掉。"""
        parser = GenericHtmlParser(
            "中国数字人文", HTTP_CFG, baseUrl="https://www.dhcn.cn/category/dhjournal/202504",
            options={k: v for k, v in self.options.items() if k != "containerSelectors"},
        )
        _, articles = parser.parseCurrentIssue(SAMPLE_GENERIC_DHCN)

        self.assertEqual([a.title for a in articles], ["迈向AI时代：数字人文基础设施的先锋之路 ——刘炜先生访谈录"])


class GenericHtmlSectionTests(unittest.TestCase):
    def testHeadingWithoutLinkIsStillASection(self):
        """栏目名本身不带链接时，照旧取到 —— 这是既有行为，不能被上面的修复打断。"""
        parser = GenericHtmlParser("中国数字人文", HTTP_CFG, baseUrl="https://example.org", options={})
        _, articles = parser.parseCurrentIssue(SAMPLE_GENERIC)

        self.assertEqual(articles[0].section, "2025年目录")


if __name__ == "__main__":
    unittest.main()
