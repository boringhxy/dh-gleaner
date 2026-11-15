"""Offline integration tests; fixtures are synthetic, not live-capture evidence."""
import json
import unittest
from unittest.mock import Mock, patch

from dhgleaner.models import Article
from dhgleaner.overseas import checkedUrl, collectSource, parseCitationPage, runSourceCapture, sourceById, sourceCatalog
from dhgleaner.paths import getPaths
from dhgleaner.service import savePending
from dhgleaner.validation import ValidationError
from dhgleaner.zotero_client import ZoteroClient
from tests.helpers import tempDataDir

PAGE = '''<meta name="citation_title" content="History and LLMs">
<meta name="citation_author" content="Test Author"><meta name="citation_date" content="2025-11-21">
<meta name="citation_doi" content="10.1234/test"><meta name="citation_firstpage" content="33">
<meta name="citation_pdf_url" content="/paper.pdf"><h2>Abstract</h2><p>Test abstract.</p>'''
VOLUME = '<h2>Volume 3, December 2025</h2><h3>Computational Humanities Research 2025</h3><a href="paper/">History and LLMs</a>'


class OverseasTests(unittest.TestCase):
    def testCatalogHasAccessEvidenceAndUniqueIds(self):
        sources = sourceCatalog()['sources']
        self.assertEqual(len({s['id'] for s in sources}), len(sources))
        for source in sources:
            self.assertEqual(source['networkAccess'], 'unknown')
            self.assertTrue(source['evidence'])
            self.assertIn('metadataAccess', source)

    def testConferenceMapping(self):
        article = parseCitationPage(PAGE, 'https://anthology.ach.org/volumes/vol0003/paper/', sourceById('chr'), 2025)
        self.assertEqual(article.itemType, 'conferencePaper')
        self.assertEqual(article.authors, ['Test Author'])
        self.assertEqual(article.abstract, 'Test abstract.')
        self.assertEqual(article.pdfUrl, 'https://anthology.ach.org/paper.pdf')
        self.assertEqual(Article.fromDict(article.toDict()).itemType, 'conferencePaper')

    def testRejectExternalAndWrongSeries(self):
        for url in ['http://journals.uio.no/dhnbpub/a', 'https://example.org/dhnbpub/a',
                    'https://journals.uio.no/other/a', 'https://user:pass@journals.uio.no/dhnbpub/a']:
            with self.assertRaises(ValidationError):
                checkedUrl(url, sourceById('dhnb'))

    def testMissingMetadataRejectsLoginPage(self):
        with self.assertRaises(ValidationError):
            parseCitationPage('<h1>Please log in</h1>', 'https://anthology.ach.org/a', sourceById('chr'), 2025)

    def testCollectionFetchesArticlesButNotPdf(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return VOLUME if url.endswith('vol0003/') else PAGE
        _, articles = collectSource('chr', 2025, {}, getHtml=fetch)
        self.assertEqual(len(articles), 1)
        self.assertFalse(any(url.endswith('.pdf') for url in calls))

    def testExplicitWrongYearDoesNotFetch(self):
        fetch = Mock()
        with self.assertRaises(ValidationError):
            collectSource('chr', 2026, {}, getHtml=fetch)
        fetch.assert_not_called()

    def testWrongConferenceIsRejected(self):
        with self.assertRaises(ValidationError):
            collectSource('chr', 2025, {}, getHtml=lambda *a, **k: '<h1>Other Conference 2025</h1>')

    def testOjsRequiresIssueNotArchive(self):
        with self.assertRaises(ValidationError):
            collectSource('dhnb', 2026, {})

    def testOjsExtractsCitationMetadata(self):
        index = '<h1>Vol. 8 No. 1 (2026)</h1><h3 class="title"><a href="https://journals.uio.no/dhnbpub/article/view/1">Paper</a></h3>'
        def fetch(url, **kw):
            return index if 'issue/view' in url else PAGE
        _, articles = collectSource('dhnb', 2026, {}, 'https://journals.uio.no/dhnbpub/issue/view/1', getHtml=fetch)
        self.assertEqual(articles[0].title, 'History and LLMs')

    def testCrossrefMetadataAndSubscriptionNote(self):
        data = {'message': {'items': [{'title': ['Test'], 'DOI': '10.1/a', 'abstract': '<p>Abstract</p>', 'author': [{'given':'A', 'family':'B'}]}]}}
        _, articles = collectSource('dsh', 2025, {}, getJson=lambda *a, **k: data)
        self.assertEqual(articles[0].authors, ['A B'])
        self.assertIn('机构订阅', articles[0].sourceNote)
        self.assertIn('不是原刊完整目录', articles[0].sourceNote)

    def testIndexOnlyFailsClearly(self):
        with self.assertRaisesRegex(ValidationError, '仅登记'):
            collectSource('jadh', 2025, {})

    def testFailedCaptureKeepsReview(self):
        with tempDataDir():
            old = Article(journal='old', year=2025, volume=None, issue=1, title='Old')
            savePending('OLD', [old])
            original = getPaths().pending.read_bytes()
            with patch('dhgleaner.overseas.fetchHtml', side_effect=RuntimeError('DNS failed')):
                with self.assertRaises(ValidationError):
                    runSourceCapture('chr', 2025, {}, dryRun=False)
            self.assertEqual(getPaths().pending.read_bytes(), original)
            self.assertEqual(getPaths().review.read_text(), 'OLD')

    def testDryRunWritesNothingAndSavedCaptureBacksUp(self):
        with tempDataDir():
            article = parseCitationPage(PAGE, 'https://anthology.ach.org/paper/', sourceById('chr'), 2025)
            with patch('dhgleaner.overseas.collectSource', return_value=(sourceById('chr'), [article])):
                runSourceCapture('chr', 2025, {}, dryRun=True)
                self.assertFalse(getPaths().pending.exists())
                savePending('OLD', [article])
                runSourceCapture('chr', 2025, {}, dryRun=False)
                self.assertTrue(list(getPaths().backupDir.glob('pending-*')))
                data = json.loads(getPaths().pending.read_text())
                self.assertEqual(data['articles'][0]['itemType'], 'conferencePaper')
                self.assertNotIn('第0期', data['markdown'])

    def testConferenceZoteroFields(self):
        client = ZoteroClient({'webLibraryId': '1', 'webApiKey': 'test'})
        client._zot = Mock()
        client._zot.item_template.return_value = {}
        client._zot.create_items.return_value = {'successful': {'0': {'key': 'TEST'}}}
        article = parseCitationPage(PAGE, 'https://anthology.ach.org/paper/', sourceById('chr'), 2025)
        client.createArticleItem(article)
        payload = client._zot.create_items.call_args.args[0][0]
        client._zot.item_template.assert_called_with('conferencePaper')
        self.assertIn('conferenceName', payload)
        self.assertNotIn('issue', payload)
        self.assertNotIn('publicationTitle', payload)
