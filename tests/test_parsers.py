"""离线解析器烟雾测试 —— 用样例 HTML 断言字段抽取，不发任何网络请求。"""

from __future__ import annotations

import unittest

from dhgleaner.parsers.cnki_cbpt import CnkiCbptParser
from dhgleaner.parsers.journy3 import Journy3Parser

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_CFG = {"userAgent": UA, "timeout": 30, "maxRetries": 3, "retryInterval": 10}

SAMPLE_JOURNY3 = """
<html><body>
<div>2026年 第6卷 第2期 刊出日期：2026-06-28</div>
<div class="wenzhanglanmu"><A name="理论探索"></A>理论探索</div>
<DIV id="art172" class="noselectrow">
  <a class="biaoti" href="/CN/Y2026/V6/I2/3">数字人文中的形式化偏向</a>
  <dd class="zuozhe">赵皓玥</dd>
  <dd class="kmnjq">2026, 6(2): 3-17.</dd>
  <a href="#1" onclick="lsdy1('PDF','172',1)">PDF</a> (9721KB)
  <div id="Abstract172" class="white_content zhaiyao">摘要文本</div>
</DIV>
</body></html>
"""

SAMPLE_CNKI = """
<html><body>
<h1>数字人文</h1>
<h1>数字史学</h1>
<ul class="column_contbox_zxlist">
  <li>
    <h3><a href="../WebPublication/paperDigest.aspx?paperID=uuid-123">历史数据可视化的路径</a></h3>
    <samp>周墨钦;王宏苏;</samp>
    <span>2025年04期  1-21页  <a href="../WebPublication/kbDownload.aspx?fn=SZRW202504001">下载</a> 3542K</span>
  </li>
</ul>
</body></html>
"""


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


if __name__ == "__main__":
    unittest.main()
