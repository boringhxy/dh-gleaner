from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import dhgleaner.capture as capture_module
import dhgleaner.cli as main_module
import dhgleaner.importer as importer_module
from dhgleaner import __version__
from dhgleaner import paths as paths_module
from dhgleaner.capture import assessCaptureQuality, resolveIssueUrl
from dhgleaner.importer import importArticles
from dhgleaner.models import Article, IssueInfo
from dhgleaner.presenter import applySelection, renderCatalog
from dhgleaner.review_spreadsheet import (
    SpreadsheetValidationError,
    exportReviewSpreadsheet,
    loadSpreadsheetSelection,
    pendingFingerprint,
)
from dhgleaner.service import CaptureOutcome
from dhgleaner.state import StateManager
from dhgleaner.title_matcher import (
    allTitleMatchesConfirmed,
    articlesFromTitleMatches,
    matchTitlesToArticles,
    normalizeTitle,
    parseTitleList,
    renderTitleMatchReport,
    selectionStringFromTitleMatches,
)
from dhgleaner.zotero_client import ZoteroClient

try:
    from .helpers import pendingPayload, tempDataDir, writePending
except ImportError:  # 直接以脚本方式运行时
    from helpers import pendingPayload, tempDataDir, writePending
try:
    from .samples import (
        HTTP_CFG,
        SAMPLE_CNKI,
        SAMPLE_GENERIC,
        SAMPLE_JOURNY3,
        SAMPLE_MAGTECH,
        UA,
    )
except ImportError:
    from samples import (
        HTTP_CFG,
        SAMPLE_CNKI,
        SAMPLE_GENERIC,
        SAMPLE_JOURNY3,
        SAMPLE_MAGTECH,
        UA,
    )
from dhgleaner.parsers.cnki_cbpt import CnkiCbptParser
from dhgleaner.parsers.generic_html import GenericHtmlParser
from dhgleaner.parsers.journy3 import Journy3Parser
from dhgleaner.parsers.magtech import MagtechParser


class FakeZotero:
    def __init__(self, collection_exists: bool = True, import_status: str = "imported"):
        self.collection_exists = collection_exists
        self.import_status = import_status
        self.items_called = False
        self.import_calls = 0

    def testConnection(self):
        return True

    def locateJournalCollection(self, journalName):
        return "COL" if self.collection_exists else None

    def importArticle(self, article, pdfPath=None, collectionKey=None, pdfUrlForNote=""):
        self.import_calls += 1
        return {"status": self.import_status, "key": f"k-{article.title}", "reason": "ok"}


class AgentTests(unittest.TestCase):
    def test_parsers_sample_html(self):
        issue1, arts1 = Journy3Parser("数字人文研究", HTTP_CFG).parseCurrentIssue(SAMPLE_JOURNY3)
        issue2, arts2 = CnkiCbptParser("数字人文", HTTP_CFG).parseCurrentIssue(SAMPLE_CNKI)
        self.assertEqual(issue1.issueTag(), "2026-Vol6-No2")
        self.assertEqual(arts1[0].articleUrl, "http://dhr.ruc.edu.cn/CN/Y2026/V6/I2/3")
        self.assertEqual(issue2.issueTag(), "2025-No4")
        self.assertTrue(arts2[0].pdfUrl.endswith("fn=SZRW202504001"))

    def test_new_journal_parsers_sample_html(self):
        issue, arts = MagtechParser("图书馆论坛", HTTP_CFG, baseUrl="http://tsglt.zslib.com.cn").parseCurrentIssue(SAMPLE_MAGTECH)
        self.assertEqual(issue.issueTag(), "2025-Vol45-No10")
        self.assertEqual(arts[0].title, "“十五五”时期图书馆的生成式AI战略")
        self.assertEqual(arts[0].authors[:2], ["曹树金", "石佳"])
        self.assertEqual(arts[0].abstract, "生成式AI摘要文本")
        self.assertIn("downloadArticleFile", arts[0].pdfUrl)

        issue2, arts2 = GenericHtmlParser("中国数字人文", HTTP_CFG, baseUrl="https://example.org").parseCurrentIssue(SAMPLE_GENERIC)
        self.assertEqual(issue2.year, 2025)
        self.assertEqual(arts2[0].articleUrl, "https://example.org/article/a1")


    def test_magtech_resolves_history_url_from_archive(self):
        cfg = {
            "name": "图书馆论坛",
            "url": "http://tsglt.zslib.com.cn/",
            "currentIssueUrl": "http://tsglt.zslib.com.cn/CN/1002-1167/current.shtml",
            "archiveUrl": "http://tsglt.zslib.com.cn/CN/article/showOldVolumn.do",
            "parser": "magtech",
            "historyUrlTemplate": "http://tsglt.zslib.com.cn/CN/Y{year}/V{volume}/I{issue}",
            "volumeYearBase": 2026,
            "volumeBase": 46,
        }
        archive = '<html><a href="/CN/Y2024/V44/I1">2024年 第44卷 第1期</a></html>'

        def fake_fetch(url, *args, **kwargs):
            if url == cfg["currentIssueUrl"]:
                return SAMPLE_MAGTECH
            if url == cfg["archiveUrl"]:
                return archive
            raise AssertionError(url)

        original = capture_module.fetchHtml
        try:
            capture_module.fetchHtml = fake_fetch
            url = resolveIssueUrl(cfg, HTTP_CFG, target={"year": 2024, "issue": 1})
        finally:
            capture_module.fetchHtml = original

        self.assertEqual(url, "http://tsglt.zslib.com.cn/CN/Y2024/V44/I1")

    def test_magtech_history_url_template_fallback_computes_volume(self):
        cfg = {
            "name": "图书馆论坛",
            "url": "http://tsglt.zslib.com.cn/",
            "currentIssueUrl": "http://tsglt.zslib.com.cn/CN/1002-1167/current.shtml",
            "archiveUrl": "http://tsglt.zslib.com.cn/CN/article/showOldVolumn.do",
            "parser": "magtech",
            "historyUrlTemplate": "http://tsglt.zslib.com.cn/CN/Y{year}/V{volume}/I{issue}",
            "volumeYearBase": 2026,
            "volumeBase": 46,
        }

        def fake_fetch(url, *args, **kwargs):
            if url == cfg["currentIssueUrl"]:
                return SAMPLE_MAGTECH
            if url == cfg["archiveUrl"]:
                return "<html><body>no matching issue</body></html>"
            raise AssertionError(url)

        original = capture_module.fetchHtml
        try:
            capture_module.fetchHtml = fake_fetch
            url = resolveIssueUrl(cfg, HTTP_CFG, target={"year": 2024, "issue": 1})
        finally:
            capture_module.fetchHtml = original

        self.assertEqual(url, "http://tsglt.zslib.com.cn/CN/Y2024/V44/I1")

    def test_magtech_missing_volume_base_explains_itself(self):
        """模板含 {volume} 却没配 volumeYearBase/volumeBase 时，报错要指出缺什么。

        过去这种情况 manualHint 是空串，用户只看到「未找到某期」，
        既不知道是配置缺口，也不知道下一步该用 --url。
        """
        cfg = {
            "name": "图书馆杂志",
            "url": "https://www.libraryjournal.com.cn/",
            "currentIssueUrl": "https://www.libraryjournal.com.cn/CN/1000-4254/current.shtml",
            "archiveUrl": "https://www.libraryjournal.com.cn/CN/article/showOldVolumn.do",
            "parser": "magtech",
            "historyUrlTemplate": "https://www.libraryjournal.com.cn/CN/Y{year}/V{volume}/I{issue}",
        }

        def fake_fetch(url, *args, **kwargs):
            if url == cfg["currentIssueUrl"]:
                return SAMPLE_MAGTECH
            if url == cfg["archiveUrl"]:
                return "<html><body>no matching issue</body></html>"
            raise AssertionError(url)

        original = capture_module.fetchHtml
        try:
            capture_module.fetchHtml = fake_fetch
            with self.assertRaises(RuntimeError) as ctx:
                resolveIssueUrl(cfg, HTTP_CFG, target={"year": 2026, "issue": 10})
        finally:
            capture_module.fetchHtml = original

        message = str(ctx.exception)
        self.assertIn("volumeYearBase", message)
        self.assertIn("--url", message)

    def test_magtech_channel_parser_pagination_issue_display_and_pdf_size(self):
        html = '''<html><body>
        <span class="item-columnName">数字人文</span>
        <script>function x(){changePage('2','60','0')}</script>
        <li class="noselectrow" id="art100">
          <a class="txt_biaoti" href="https://example.org/CN/Y2025/V44/I416/58">跨期栏目文章标题研究</a>
          <span class="abs_zuozhe_cn">张三 李四</span>
          <span class="abs_njq">图书馆杂志 2025, 44 (<strong>416</strong>): 58-67.</span>
          <a href="javascript:;" onclick="lsdy1('PDF','100')">PDF(CN)</a> （21637KB）
          <div id="Abstract100" class="white_content">摘要文本</div>
        </li>
        <div class="page-total">共63条记录</div><li>共2页</li>
        </body></html>'''
        parser = MagtechParser("图书馆杂志", HTTP_CFG, baseUrl="https://example.org")
        pages = parser.discoverChannelPageUrls(html, "https://example.org/CN/article/showChannelArticle.do?id=60")
        self.assertEqual(len(pages), 2)
        pageQs = parse_qs(urlparse(pages[-1]).query)
        self.assertEqual(pageQs.get("pager"), ["2"])
        self.assertEqual(pageQs.get("id"), ["60"])
        self.assertEqual(pageQs.get("year"), ["0"])
        issue, arts = parser.parseChannelPage(html, "数字人文")
        self.assertEqual(issue.year, 0)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].sourceType, "channel")
        self.assertEqual(arts[0].issueDisplay, "2025, 44(416)")
        self.assertEqual(arts[0].totalIssue, 416)
        self.assertEqual(arts[0].pagesStr(), "58-67")
        self.assertEqual(arts[0].pdfSize, "21637KB")
        self.assertNotIn("KBB", arts[0].pdfSize)

    def test_generic_html_filters_navigation_duplicates_and_domains(self):
        html = '''<html><body>
        <nav><a href="/home">首页</a><a href="/more">Read More</a></nav>
        <main class="content">
          <a href="https://dhcn.cn/a1">数字人文视野下的历史数据研究</a>
          <a href="https://dhcn.cn/a1">数字人文视野下的历史数据研究</a>
          <a href="https://ads.example/ad">数字人文数据库广告推荐</a>
          <a href="https://mp.weixin.qq.com/s/abc">数字人文方法与文献整理研究</a>
        </main>
        </body></html>'''
        parser = GenericHtmlParser(
            "中国数字人文",
            HTTP_CFG,
            baseUrl="https://dhcn.cn",
            options={
                "containerSelectors": ["main.content"],
                "allowedDomains": ["dhcn.cn", "mp.weixin.qq.com"],
                "titleBlacklist": ["广告"],
                "titleKeywords": ["数字人文", "历史", "文献"],
            },
        )
        _, arts = parser.parseCurrentIssue(html)
        self.assertEqual(len(arts), 2)
        self.assertTrue(all("Read More" not in a.title and "首页" not in a.title for a in arts))
        self.assertEqual({a.articleUrl for a in arts}, {"https://dhcn.cn/a1", "https://mp.weixin.qq.com/s/abc"})

    def test_capture_quality_marks_suspect_pages(self):
        issue = IssueInfo(year=0, volume=None, issue=0)
        articles = [Article(journal="测试", year=0, volume=None, issue=0, title="数字人文研究文章", articleUrl="u")]
        status, reason = assessCaptureQuality(issue, articles, captureType="issue")
        self.assertEqual(status, "suspect")
        self.assertIn("0年第0期", reason)

        goodIssue = IssueInfo(year=2025, volume=None, issue=1)
        badArticles = [
            Article(journal="测试", year=2025, volume=None, issue=1, title="Read More", articleUrl="u1"),
            Article(journal="测试", year=2025, volume=None, issue=1, title="首页", articleUrl="u2"),
            Article(journal="测试", year=2025, volume=None, issue=1, title="数字人文有效研究标题", articleUrl="u3"),
            Article(journal="测试", year=2025, volume=None, issue=1, title="另一篇数字人文研究标题", articleUrl="u4"),
        ]
        status, reason = assessCaptureQuality(goodIssue, badArticles, captureType="issue")
        self.assertEqual(status, "suspect")
        self.assertIn("占比过高", reason)

    def test_presenter_and_selection(self):
        article = Article(
            journal="数字人文研究",
            year=2026,
            volume=6,
            issue=2,
            section="理论|探索",
            title="标题|换行\n测试",
            authors=["张三", "李四"],
            abstract="摘要",
            startPage=3,
            endPage=17,
            articleUrl="http://example.com/a",
            pdfUrl="http://example.com/a.pdf",
            pdfSize="9721KB",
            publishDate="2026-06-28",
        )
        markdown, articles = renderCatalog([("数字人文研究", IssueInfo(2026, 6, 2, "2026-06-28"), [article])])
        self.assertIn("\\|", markdown)
        selected = applySelection(articles, "1")
        self.assertEqual(selected[0].title, article.title)
        self.assertEqual(selected[0].status, "selected")


    def test_title_matching_normalizes_punctuation_and_preserves_user_order(self):
        articles = [
            Article(journal="中国数字人文", year=2025, volume=None, issue=1, title="基于地方志的空间数据整理（上）", articleUrl="u1"),
            Article(journal="中国数字人文", year=2025, volume=None, issue=1, title="从晚清民国报刊看城市文化--以上海为中心", articleUrl="u2"),
        ]
        for i, article in enumerate(articles, 1):
            article._globalIndex = i
        requested = parseTitleList("1. 从晚清民国报刊看城市文化——以上海为中心\n2. 基于地方志的空间数据整理(上)")
        matches = matchTitlesToArticles(requested, articles)
        self.assertTrue(allTitleMatchesConfirmed(matches))
        self.assertEqual(selectionStringFromTitleMatches(matches), "2,1")
        selected = articlesFromTitleMatches(matches, articles)
        self.assertEqual([a.title for a in selected], [articles[1].title, articles[0].title])
        self.assertEqual(normalizeTitle("“数字人文”（A—B）"), normalizeTitle('"数字人文"(A-B)'))

    def test_title_matching_reports_unmatched(self):
        articles = [
            Article(journal="测试", year=2025, volume=None, issue=1, title="数字人文方法研究", articleUrl="u1"),
            Article(journal="测试", year=2025, volume=None, issue=1, title="数字人文资料整理", articleUrl="u2"),
        ]
        for i, article in enumerate(articles, 1):
            article._globalIndex = i
        matches = matchTitlesToArticles(["数字人文方法研究", "完全不存在的标题"], articles)
        report = renderTitleMatchReport(matches)
        self.assertEqual(matches[0].status, "matched")
        self.assertEqual(matches[1].status, "unmatched")
        self.assertIn("未匹配", report)
        self.assertFalse(allTitleMatchesConfirmed(matches))

    def test_import_aborts_on_missing_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = StateManager(str(state_path))
            article = Article(
                journal="数字人文研究",
                year=2026,
                volume=6,
                issue=2,
                section="理论探索",
                title="测试文章",
                authors=["张三"],
                articleUrl="http://example.com/a",
                pdfUrl="http://example.com/a.pdf",
                publishDate="2026-06-28",
            )
            report = importArticles(
                [article],
                FakeZotero(collection_exists=False),
                state,
                userAgent=UA,
                tempDir=tmp,
                journalConfigs={},
                allPendingArticles=[article],
            )
            self.assertIn("Collection 路径不存在", report)
            if state_path.exists():
                data = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(data["journals"], {})
            else:
                self.assertFalse(state_path.exists())

    def test_pdf_download_failure_degrades_to_metadata_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(str(Path(tmp) / "state.json"))
            article = Article(
                journal="数字人文研究",
                year=2026,
                volume=6,
                issue=2,
                title="PDF失败但条目保留",
                authors=["张三"],
                abstract="已有摘要",
                articleUrl="http://example.com/a",
                pdfUrl="http://example.com/a.pdf",
            )

            class CaptureZotero(FakeZotero):
                def __init__(self):
                    super().__init__()
                    self.pdf_url_for_note = None
                    self.fail_reason = None

                def importArticle(self, article, pdfPath=None, collectionKey=None, pdfUrlForNote=""):
                    self.pdf_url_for_note = pdfUrlForNote
                    self.fail_reason = article.failReason
                    return {"status": "imported", "key": "k1", "reason": "条目已创建，PDF需手动下载"}

            def failing_download(*args, **kwargs):
                raise RuntimeError("network blocked")

            original = importer_module.downloadFile
            zotero = CaptureZotero()
            try:
                importer_module.downloadFile = failing_download
                report = importArticles(
                    [article],
                    zotero,
                    state,
                    userAgent=UA,
                    tempDir=tmp,
                    journalConfigs={"数字人文研究": {"autoDownloadPdf": True}},
                    allPendingArticles=[article],
                )
            finally:
                importer_module.downloadFile = original

            self.assertIn("成功: 1 篇", report)
            self.assertEqual(zotero.pdf_url_for_note, "http://example.com/a.pdf")
            self.assertIn("PDF下载失败", zotero.fail_reason)


    def test_zotero_records_pdf_link_when_attachment_upload_fails(self):
        article = Article(
            journal="图书馆论坛",
            year=2026,
            volume=46,
            issue=7,
            title="PDF上传失败但记录链接",
            authors=["张三"],
            articleUrl="http://example.com/a",
            pdfUrl="http://example.com/a.pdf",
        )

        class FakeClient(ZoteroClient):
            def __init__(self):
                super().__init__({})
                self.url_attached = False
                self.extra_text = ""

            def checkDuplicate(self, article):
                return None

            def createArticleItem(self, article, collectionKey=None, extraText="", extraTags=None):
                self.extra_text = extraText
                return "ITEM1"

            def attachPdf(self, itemKey, pdfPath, title="全文PDF"):
                return False

            def attachUrl(self, itemKey, url, title="PDF下载链接"):
                self.url_attached = (itemKey == "ITEM1" and url == "http://example.com/a.pdf")
                return self.url_attached

        article.issueDisplay = "2026, 46(7)"
        article.sourceType = "channel"
        article.sourceNote = "栏目页抓取"
        client = FakeClient()
        result = client.importArticle(article, pdfPath="/tmp/fake.pdf", collectionKey="COL")
        self.assertEqual(result["status"], "imported")
        self.assertTrue(result["pdfLinkRecorded"])
        self.assertIn("已记录下载链接", result["reason"])
        self.assertTrue(client.url_attached)
        self.assertIn("原站年卷期: 2026, 46(7)", client.extra_text)
        self.assertIn("来源类型: channel", client.extra_text)
        self.assertIn("来源说明: 栏目页抓取", client.extra_text)

    def test_skip_all_marks_articles_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = StateManager(str(state_path))
            articles = [
                Article(journal="数字人文研究", year=2026, volume=6, issue=2, title="A", articleUrl="u:a"),
                Article(journal="数字人文研究", year=2026, volume=6, issue=2, title="B", articleUrl="u:b"),
            ]
            for article in articles:
                state.markArticleProcessed(article.journal, article.articleKey(), title=article.title, status="skipped")
            state.markIssueProcessed("数字人文研究", articles[0].issueInfo())
            data = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("u:a", data["journals"]["数字人文研究"]["processedArticles"])
            self.assertIsNotNone(data["journals"]["数字人文研究"]["lastIssue"])

    def test_review_spreadsheet_round_trips_selected_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            articles = [
                Article(
                    journal="数字人文研究",
                    year=2026,
                    volume=6,
                    issue=2,
                    section="理论探索",
                    title="数字人文中的形式化偏向",
                    authors=["赵皓玥"],
                    abstract="摘要文本",
                    startPage=3,
                    endPage=17,
                    articleUrl="http://example.com/a",
                    pdfUrl="http://example.com/a.pdf",
                ),
                Article(
                    journal="数字人文研究",
                    year=2026,
                    volume=6,
                    issue=2,
                    section="方法",
                    title="空间叙事与历史地理",
                    authors=["李四"],
                    articleUrl="http://example.com/b",
                ),
            ]
            for i, article in enumerate(articles, 1):
                article._globalIndex = i

            pending = {
                "capturedAt": "2026-07-20T10:00:00+08:00",
                "captureType": "issue",
                "note": "测试",
            }
            path = Path(tmp) / "review_selection.xlsx"
            exportReviewSpreadsheet(path, articles, pending, selectedIndexes=[1])

            selected = loadSpreadsheetSelection(path, articles, pending)
            self.assertEqual([article.title for article in selected], [articles[0].title])
            self.assertGreater(path.stat().st_size, 1000)

    def test_review_spreadsheet_rejects_stale_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            articles = [
                Article(journal="数字人文研究", year=2026, volume=6, issue=2, title="A", articleUrl="u:a"),
            ]
            articles[0]._globalIndex = 1
            pending = {"capturedAt": "2026-07-20T10:00:00+08:00", "captureType": "issue"}
            path = Path(tmp) / "review_selection.xlsx"
            exportReviewSpreadsheet(path, articles, pending)

            changed = {"capturedAt": "2026-07-20T11:00:00+08:00", "captureType": "issue"}
            self.assertNotEqual(pendingFingerprint(articles, pending), pendingFingerprint(articles, changed))
            with self.assertRaises(SpreadsheetValidationError):
                loadSpreadsheetSelection(path, articles, changed)

    def test_export_review_command_writes_xlsx(self):
        with tempDataDir():
            writePending(pendingPayload([{
                "journal": "数字人文研究",
                "year": 2026,
                "volume": 6,
                "issue": 2,
                "title": "数字人文中的形式化偏向",
                "authors": ["赵皓玥"],
                "abstract": "摘要文本",
                "articleUrl": "http://example.com/a",
                "pdfUrl": "http://example.com/a.pdf",
                "_globalIndex": 1,
            }]))

            args = type("Args", (), {"format": "xlsx", "output": ""})()
            # 结果文案是中文，而这两个用例直接调 cmd* 函数、不经过 main()，
            # 拿不到 main() 里的 UTF-8 修正；Windows 控制台默认 cp1252 会直接抛错。
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                main_module.cmdExportReview(args, {"http": {}, "journals": []})

            self.assertTrue(paths_module.getPaths().spreadsheet.exists())
            self.assertIn("筛选表已保存到", buffer.getvalue())

    def test_import_spreadsheet_uses_selected_rows(self):
        with tempDataDir():
            payload = pendingPayload([
                {
                    "journal": "数字人文研究",
                    "year": 2026,
                    "volume": 6,
                    "issue": 2,
                    "title": "数字人文中的形式化偏向",
                    "authors": ["赵皓玥"],
                    "abstract": "摘要文本",
                    "articleUrl": "http://example.com/a",
                    "pdfUrl": "http://example.com/a.pdf",
                    "_globalIndex": 1,
                },
                {
                    "journal": "数字人文研究",
                    "year": 2026,
                    "volume": 6,
                    "issue": 2,
                    "title": "空间叙事与历史地理",
                    "authors": ["李四"],
                    "abstract": "",
                    "articleUrl": "http://example.com/b",
                    "pdfUrl": "",
                    "_globalIndex": 2,
                },
            ])
            writePending(payload)
            spreadsheet = paths_module.getPaths().spreadsheet
            exportReviewSpreadsheet(
                spreadsheet,
                [Article.fromDict(a) for a in payload["articles"]],
                payload,
                selectedIndexes=[2],
            )

            captured = {}
            original_run_import = main_module._runImport

            def fake_run_import(selected, articles, markdown, cfg):
                captured["titles"] = [article.title for article in selected]
                return "ok"

            main_module._runImport = fake_run_import
            buffer = io.StringIO()
            try:
                args = type("Args", (), {
                    "selection": None,
                    "titles": None,
                    "titles_file": None,
                    "confirm_titles": False,
                    "all": False,
                    "spreadsheet": str(spreadsheet),
                    "dry_run": False,
                })()
                # 同上：cmdImport 的进度文案是中文，直接用 Windows 控制台流会抛
                # UnicodeEncodeError，这里把输出接走再断言。
                with redirect_stdout(buffer):
                    main_module.cmdImport(args, {"http": {}, "journals": [], "zotero": {}})
            finally:
                main_module._runImport = original_run_import

            self.assertEqual(captured["titles"], ["空间叙事与历史地理"])
            self.assertIn("到 Zotero...", buffer.getvalue())
            self.assertIn("ok", buffer.getvalue())

    def testCliVersionFlagMatchesPackageVersion(self):
        """bug 模板要求使用者贴版本号，所以 --version 必须存在且与包内一致。"""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with mock.patch.object(sys, "argv", ["dhgleaner", "--version"]):
                with self.assertRaises(SystemExit) as ctx:
                    main_module.main()
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buffer.getvalue().strip(), f"dh-gleaner {__version__}")


class CaptureExitCodeTests(unittest.TestCase):
    """抓取命令必须能用退出码判断成败，cron / CI 才知道这次算不算数。"""

    def outcome(self, status: str):
        return CaptureOutcome(
            journal="测试刊",
            issue="2026年 第6卷 第2期",
            markdown="# 清单",
            articles=[],
            quality=status,
            reason="测试原因",
            status=status,
            collected=[],
        )

    def testStatusMapsToDistinctCodes(self):
        self.assertEqual(main_module._captureExitCode(self.outcome("success")), 0)
        self.assertEqual(main_module._captureExitCode(self.outcome("suspect")), 3)
        self.assertEqual(main_module._captureExitCode(self.outcome("failed")), 1)

    def runCaptureMain(self, status: str):
        argv = ["dhgleaner", "capture", "--journal", "图书馆论坛", "--year", "2026", "--issue", "2"]
        original = main_module.captureIssue
        originalLogging = main_module.setupLogging
        try:
            with tempDataDir():
                main_module.captureIssue = lambda *a, **k: self.outcome(status)
                # main() 里的 setDataDir(None) 会重算数据目录并落回当前工作目录，
                # 真跑 setupLogging 就会打开仓库里的 logs/capture.log。
                main_module.setupLogging = lambda *a, **k: None
                with redirect_stdout(io.StringIO()):
                    with mock.patch.object(sys, "argv", argv):
                        main_module.main()
        finally:
            main_module.captureIssue = original
            main_module.setupLogging = originalLogging

    def testFailedCaptureExitsNonZero(self):
        with self.assertRaises(SystemExit) as ctx:
            self.runCaptureMain("failed")
        self.assertEqual(ctx.exception.code, 1)

    def testSuspectCaptureExitsWithItsOwnCode(self):
        with self.assertRaises(SystemExit) as ctx:
            self.runCaptureMain("suspect")
        self.assertEqual(ctx.exception.code, 3)

    def testSuccessfulCaptureDoesNotExit(self):
        self.runCaptureMain("success")


if __name__ == "__main__":
    unittest.main()
