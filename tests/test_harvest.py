"""散篇 harvest 离线测试 —— 关键词打标、前置条目过滤、各皮肤解析、harvest 过滤。

全部用样例 HTML/JSON 与桩解析器，不发任何网络请求、不写 Zotero。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from dhgleaner import harvest as harvest_module
from dhgleaner.keywords import dhHits, historyAiHits, isDh, tagArticles
from dhgleaner.models import Article
from dhgleaner.parsers.founder import FounderParser
from dhgleaner.parsers.journalx import JournalXParser
from dhgleaner.parsers.magtech import MagtechParser
from dhgleaner.state import StateManager
from dhgleaner.textutil import cleanText, isFrontMatterTitle
from tests.helpers import tempDataDir

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_CFG = {"userAgent": UA, "timeout": 30, "maxRetries": 1, "retryInterval": 0, "harvestDelay": 0}


def _article(**kwargs) -> Article:
    base = {"journal": "测试", "year": 2026, "volume": None, "issue": 1, "title": ""}
    base.update(kwargs)
    return Article(**base)


class KeywordTaggingTests(unittest.TestCase):
    def testDigitalHumanitiesAnyHit(self):
        article = _article(title="数字人文视域下的古籍整理研究")
        tagArticles([article])
        self.assertIn("数字人文", article.dhMatched)
        self.assertTrue(isDh(article))

    def testHistoryAiRequiresCooccurrence(self):
        article = _article(title="基于深度学习的甲骨文字识别方法")
        tagArticles([article])
        self.assertTrue(article.histAiMatched, "历史词与计算词共现时应命中")
        self.assertIn("甲骨", article.histAiMatched)
        self.assertTrue(isDh(article))

    def testPureHistoryWithoutComputeIsNotCollected(self):
        article = _article(title="明清社会经济史札记")
        tagArticles([article])
        self.assertEqual(article.histAiMatched, [])
        self.assertEqual(article.dhMatched, [])
        self.assertFalse(isDh(article))

    def testTrapWordsAreExcluded(self):
        article = _article(title="历史研究的新路径", abstract="关于传统文化与记忆的论述")
        tagArticles([article])
        self.assertEqual(article.dhMatched, [])
        self.assertEqual(article.histAiMatched, [])
        self.assertFalse(isDh(article))

    def testEnglishAcronymsAreCaseSensitive(self):
        article = _article(title="A storage logistics system", abstract="warehouse and storage management")
        self.assertEqual(dhHits(article), [])
        self.assertEqual(historyAiHits(article), [])

    def testHistoryAiHitsEmptyWithoutBothSides(self):
        onlyHistory = _article(title="敦煌出土文献研究")
        self.assertEqual(historyAiHits(onlyHistory), [])

    def testPureComputeWordsNoLongerCountAsDh(self):
        """收紧(b)：纯 AI 方法词（无领域词、无历史共现）不算 DH。"""
        article = _article(title="生成式人工智能驱动的情报检索范式转型", abstract="基于大语言模型与知识图谱的方法")
        tagArticles([article])
        self.assertEqual(article.dhMatched, [])
        self.assertEqual(article.histAiMatched, [])
        self.assertFalse(isDh(article))

    def testBroadComputeWordsAloneAreNotDh(self):
        """收紧(a)：本体/语义/可视化 单独命中不再算 DH。"""
        for title in ("企业产品在线评论本体构建研究", "科学文献语义表示方法", "科研数据可视化平台设计"):
            article = _article(title=title)
            tagArticles([article])
            self.assertEqual(article.dhMatched, [], title)
            self.assertFalse(isDh(article), title)

    def testBroadComputeWordsStillServeHistoryCooccurrence(self):
        """收紧(a) 的另一面：本体/语义 仍可作为「历史+AI」共现的计算侧。"""
        article = _article(title="基于语义的古籍知识组织研究")
        tagArticles([article])
        self.assertIn("古籍", article.histAiMatched)
        self.assertTrue(article.histAiMatched)
        self.assertTrue(isDh(article))

    def testDhFieldWordAloneStillCounts(self):
        """领域词单独命中仍算 DH（数字人文/文化遗产/博物馆/GLAM 等）。"""
        for title in ("数字人文视域下的古籍整理", "文化遗产数字资源建设", "面向GLAM的开放数据实践"):
            article = _article(title=title)
            tagArticles([article])
            self.assertTrue(article.dhMatched, title)
            self.assertTrue(isDh(article), title)


class TextUtilTests(unittest.TestCase):
    def testCleanTextStripsMagtechPlaceholders(self):
        self.assertEqual(cleanText("标题#br#换行#b#结尾"), "标题 换行 结尾")

    def testCleanTextStripsPrivateUseChars(self):
        self.assertEqual(cleanText("甲\ue000乙"), "甲 乙")

    def testFrontMatterDetection(self):
        for title in ("目次", "封面", "卷首语", "征稿启事", "摘要", "编委会"):
            self.assertTrue(isFrontMatterTitle(title), title)
        for title in ("数字人文视域下的古籍整理", "明清经济史"):
            self.assertFalse(isFrontMatterTitle(title), title)


class FounderParserTests(unittest.TestCase):
    def testOneArticleMapsApiFields(self):
        parser = FounderParser("现代情报", HTTP_CFG, {"siteId": 1084})
        item = {
            "resName": "基于知识图谱的古籍可视化研究",
            "authors": "张三;李四；王五",
            "summary": "本文利用知识图谱技术对古籍进行可视化组织。",
            "keyword": "知识图谱;古籍;可视化",
            "firstPageNum": "6",
            "lastPageNum": "15",
            "doi": "10.1234/xdqb.2026.03.006",
            "year": "2026",
            "volume": "43",
            "issue": "3",
            "part": "专题研究",
        }
        article = parser._oneArticle(item, year=2026, issue=3, volume=43, columnName="默认栏目")
        self.assertEqual(article.title, "基于知识图谱的古籍可视化研究")
        self.assertEqual(article.authors, ["张三", "李四", "王五"])
        self.assertEqual(article.keywords, "知识图谱;古籍;可视化")
        self.assertEqual(article.section, "专题研究")
        self.assertEqual((article.startPage, article.endPage), (6, 15))
        self.assertEqual(article.articleUrl, "https://doi.org/10.1234/xdqb.2026.03.006")
        self.assertEqual(article.issueDisplay, "2026, 43(3)")
        self.assertEqual(article.sourceType, "harvest")

    def testOneArticleWithoutVolume(self):
        parser = FounderParser("现代情报", HTTP_CFG, {"siteId": 1084})
        article = parser._oneArticle({"resName": "标题", "year": "2026", "issue": "3"}, 2026, 3, None, "")
        self.assertEqual(article.issueDisplay, "2026(3)")
        self.assertEqual(article.articleUrl, "")

    def testParseCurrentIssueIsUnsupported(self):
        parser = FounderParser("现代情报", HTTP_CFG, {"siteId": 1084})
        with self.assertRaises(NotImplementedError):
            parser.parseCurrentIssue("<html></html>")


class JournalXRowTests(unittest.TestCase):
    LIST_HTML = """
    <table>
      <tr><td><a href="view_abstract.aspx?file_no=20260101">数字人文视域下的古籍整理</a></td></tr>
      <tr><td>张三，李四</td></tr>
      <tr><td>2026, 52(1): 3-17.</td></tr>
      <tr><td><a href="view_abstract.aspx?file_no=20260102">目次</a></td></tr>
      <tr><td><a href="view_abstract.aspx?file_no=20260101">数字人文视域下的古籍整理</a></td></tr>
      <tr><td>王五</td></tr>
      <tr><td>2026, 52(1): 3-17.</td></tr>
    </table>
    """

    def testRowsDedupeAndSkipFrontMatter(self):
        parser = JournalXParser("中国图书馆学报", HTTP_CFG, baseUrl="https://www.jlis.cn/jtlsc/ch/reader/")
        rows = parser._rows(BeautifulSoup(self.LIST_HTML, "lxml"), year=2026, quarter=1)
        self.assertEqual(len(rows), 1, "前置条目与重复 file_no 都应被跳过")
        article = rows[0]
        self.assertEqual(article.title, "数字人文视域下的古籍整理")
        self.assertEqual(article.authors, ["张三", "李四"])
        self.assertEqual((article.year, article.volume, article.issue), (2026, 52, 1))
        self.assertEqual((article.startPage, article.endPage), (3, 17))
        self.assertEqual(article.issueDisplay, "2026, 52(1)")
        self.assertEqual(article.sourceType, "harvest")
        self.assertTrue(article.articleUrl.startswith("https://www.jlis.cn/jtlsc/ch/reader/"))


class MagtechSkinTests(unittest.TestCase):
    LUNWEN_HTML = """
    <ul class="lunwen">
      <li class="biaoti"><a href="/CN/abstract/abstract1.shtml">数字人文视域下的古籍整理</a></li>
      <li class="zuozhe">张三,李四</li>
      <li>2026 Vol.52 (1): 3-17.</li>
    </ul>
    """

    DQML_HTML = """
    <div class="dqml">
      <div class="dqml_bt"><a href="/CN/10.13366/j.dik.2026.03.006">基于知识图谱的古籍可视化</a></div>
      <div class="dqml_wzn">张三，李四 2026, 43 (3): 6-15. doi:10.13366/j.dik.2026.03.006</div>
      <a href="/CN/abstract">摘要</a> <a href="/CN/pdf">PDF</a>
    </div>
    """

    def testParseLunwenList(self):
        parser = MagtechParser("情报科学", HTTP_CFG, baseUrl="https://journal12.magtechjournal.com/jwk3_qbkx")
        articles = parser._parseLunwenList(BeautifulSoup(self.LUNWEN_HTML, "lxml"))
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "数字人文视域下的古籍整理")
        self.assertEqual(article.authors, ["张三", "李四"])
        self.assertEqual((article.year, article.volume, article.issue), (2026, 52, 1))
        self.assertEqual((article.startPage, article.endPage), (3, 17))
        self.assertEqual(article.sourceType, "harvest")

    def testParseDqmlList(self):
        parser = MagtechParser("图书情报知识", HTTP_CFG, baseUrl="https://dik.whu.edu.cn/jwk3/tsqbzs")
        articles = parser._parseDqmlList(BeautifulSoup(self.DQML_HTML, "lxml"))
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "基于知识图谱的古籍可视化")
        self.assertEqual(article.authors, ["张三", "李四"])
        self.assertEqual((article.year, article.volume, article.issue), (2026, 43, 3))
        self.assertEqual((article.startPage, article.endPage), (6, 15))
        self.assertEqual(article.doi, "10.13366/j.dik.2026.03.006")
        self.assertEqual(article.sourceType, "harvest")

    def testVolumnPageDetectsLunwenSkin(self):
        parser = MagtechParser("情报科学", HTTP_CFG, baseUrl="https://journal12.magtechjournal.com/jwk3_qbkx")
        articles = parser._parseVolumnPage(BeautifulSoup(self.LUNWEN_HTML, "lxml"))
        self.assertEqual([a.title for a in articles], ["数字人文视域下的古籍整理"])

    def testVolumnPageDetectsDqmlSkin(self):
        parser = MagtechParser("图书情报知识", HTTP_CFG, baseUrl="https://dik.whu.edu.cn/jwk3/tsqbzs")
        articles = parser._parseVolumnPage(BeautifulSoup(self.DQML_HTML, "lxml"))
        self.assertEqual([a.title for a in articles], ["基于知识图谱的古籍可视化"])


class _StubParser:
    """桩解析器：返回 DH 散篇 / 纯历史散篇 / 前置条目各一篇。"""

    supportsHarvest = True

    def __init__(self, journalName, httpCfg, journalCfg=None):
        self.journalName = journalName

    def harvestYear(self, year, *, withAbstracts=True):
        from dhgleaner.models import IssueInfo
        articles = [
            _article(title="数字人文视域下的古籍整理", journal=self.journalName),
            _article(title="明清社会经济史札记", journal=self.journalName),
            _article(title="目次", journal=self.journalName),
        ]
        return IssueInfo(year=year, volume=None, issue=0), articles


class HarvestFlowTests(unittest.TestCase):
    def setUp(self):
        self._origGetParser = harvest_module.getParser
        harvest_module.getParser = lambda *a, **k: _StubParser(a[1], a[2], a[3] if len(a) > 3 else None)
        self.addCleanup(self._restore)

    def _restore(self):
        harvest_module.getParser = self._origGetParser

    def testDhOnlyKeepsTaggedHitsAndDropsFrontMatter(self):
        with tempDataDir() as dataDir:
            state = StateManager(str(Path(dataDir) / "state.json"))
            cfg = {"name": "测试散刊", "parser": "magtech", "harvestOnly": True}
            issue, articles, failure = harvest_module.harvestJournal(
                cfg, HTTP_CFG, state, year=2026, dhOnly=True
            )
            titles = [a.title for a in articles]
            self.assertEqual(titles, ["数字人文视域下的古籍整理"])
            self.assertTrue(articles[0].dhMatched)
            self.assertTrue(all(a.capturedAt for a in articles))
            self.assertIsNone(failure, "筛完只剩一篇是合法结果，不该记为失败")

    def testAllCatalogKeepsBothRealArticlesWithTagging(self):
        with tempDataDir() as dataDir:
            state = StateManager(str(Path(dataDir) / "state.json"))
            cfg = {"name": "测试散刊", "parser": "magtech", "harvestOnly": True}
            issue, articles, failure = harvest_module.harvestJournal(
                cfg, HTTP_CFG, state, year=2026, dhOnly=False
            )
            titles = [a.title for a in articles]
            self.assertEqual(titles, ["数字人文视域下的古籍整理", "明清社会经济史札记"])
            self.assertTrue(articles[0].dhMatched)
            self.assertEqual(articles[1].dhMatched, [])
            self.assertIsNone(failure)

    def testHarvestAllSelectsOnlyHarvestJournalsByDefault(self):
        with tempDataDir() as dataDir:
            state = StateManager(str(Path(dataDir) / "state.json"))
            journals = [
                {"name": "测试散刊", "parser": "magtech", "harvestOnly": True},
                {"name": "普通刊", "parser": "magtech"},
            ]
            results, failures = harvest_module.harvestAll(journals, HTTP_CFG, state, year=2026, dhOnly=True)
            self.assertEqual([name for name, _, _ in results], ["测试散刊"])
            self.assertEqual(failures, [])

    def testIsHarvestJournal(self):
        self.assertTrue(harvest_module.isHarvestJournal({"harvestOnly": True}))
        self.assertFalse(harvest_module.isHarvestJournal({}))


if __name__ == "__main__":
    unittest.main()
