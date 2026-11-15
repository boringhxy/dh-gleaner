"""Public overseas DH sources. Capture never downloads PDFs or signs into institutions."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .http_util import fetchHtml, fetchJson
from .models import Article, IssueInfo
from .presenter import renderCatalog
from .validation import ValidationError


def sourceCatalog():
    return json.loads((Path(__file__).parent / 'defaults' / 'overseas_sources.json').read_text(encoding='utf-8'))


def sourceById(sourceId):
    for source in sourceCatalog()['sources']:
        if source['id'] == sourceId:
            return source
    raise ValidationError(f'未知海外来源：{sourceId}；请运行 sources 查看来源ID。')


def checkedUrl(url, source):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValidationError('仅接受来源官方域名的HTTPS地址。')
    if parsed.hostname not in source.get('allowedHosts', []):
        raise ValidationError('地址不在该来源的官方域名白名单中。')
    if source.get('pathPrefix') and not parsed.path.startswith(source['pathPrefix']):
        raise ValidationError('地址不属于该出版系列。')
    return url


def _text(value):
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)


def _meta(soup, name):
    return [m.get('content', '').strip() for m in soup.select(f'meta[name="{name}"]') if m.get('content')]


def parseCitationPage(html, url, source, year):
    """Highwire citation metadata shared by OJS and scholarly publication platforms."""
    soup = BeautifulSoup(html, 'lxml')
    def first(name):
        values = _meta(soup, name)
        return values[0] if values else ''
    title = first('citation_title')
    if not title:
        raise ValidationError(f'文章页缺少citation_title，可能是登录或拦截页面：{url}')
    date = first('citation_publication_date') or first('citation_date')
    published = re.search(r'\b(19\d{2}|20\d{2})\b', date)
    abstract = first('DC.Description') or first('DC.description') or first('description')
    node = soup.select_one('.item.abstract, section.abstract, #abstract')
    if node:
        abstract = node.get_text(' ', strip=True)
        abstract = re.sub(r'^Abstract\s*', '', abstract, flags=re.I)
    # Anthology puts its abstract below a heading; extract only following siblings.
    if not abstract:
        heading = soup.find(re.compile('^h[1-6]$'), string=re.compile(r'^Abstract$', re.I))
        if heading:
            blocks = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ('footer', 'h1', 'h2', 'h3'):
                    break
                if sibling.name == 'p':
                    blocks.append(sibling.get_text(' ', strip=True))
            abstract = ' '.join(blocks)
    conference = source['kind'] != 'journal'
    item = Article(journal=source['name'], year=int(published.group(1)) if published else year,
                   volume=int(first('citation_volume')) if first('citation_volume').isdigit() else None,
                   issue=int(first('citation_issue')) if first('citation_issue').isdigit() else 0,
                   title=title, authors=_meta(soup, 'citation_author'), abstract=_text(abstract),
                   doi=first('citation_doi').removeprefix('https://doi.org/'),
                   articleUrl=url, pdfUrl=urljoin(url, first('citation_pdf_url')) if first('citation_pdf_url') else '',
                   publishDate=date, issueDisplay=source.get("contextLabel", f"{source['name']} {year}"), sourceType='conference' if conference else 'overseas',
                   sourceNote=_accessNote(source), itemType='conferencePaper' if conference else 'journalArticle')
    for key, field in [('citation_firstpage', 'startPage'), ('citation_lastpage', 'endPage')]:
        value = first(key)
        if value.isdigit():
            setattr(item, field, int(value))
    return item


def _accessNote(source):
    return ('题录：公开；全文：' + source['fulltextAccess'] + '。' + source.get('accessNote', '')
            + source.get('note', '') + ' ' + source['networkNote'])


def _crossref(source, year, getJson, options):
    articles, cursor = [], '*'
    for _ in range(20):
        params = {'filter': f'from-pub-date:{year}-01-01,until-pub-date:{year}-12-31',
                  'rows': 100, 'cursor': cursor}
        url = f"https://api.crossref.org/journals/{source['issn']}/works?{urlencode(params)}"
        message = getJson(url, **options).get('message', {})
        items = message.get('items', [])
        for item in items:
            titles = item.get('title') or []
            if not titles:
                continue
            article = Article(journal=source['name'], year=year, volume=None, issue=0,
                              title=_text(titles[0]), authors=[a.get('name') or ' '.join(filter(None, [a.get('given'), a.get('family')])) for a in item.get('author', [])],
                              abstract=_text(item.get('abstract', '')), doi=item.get('DOI', ''),
                              articleUrl='https://doi.org/' + item['DOI'] if item.get('DOI') else item.get('URL', ''),
                              issueDisplay=f"{source['name']} {year} / Crossref", sourceType='overseas',
                              sourceNote=_accessNote(source) + ' Crossref结果不是原刊完整目录。')
            parts = (item.get('published', {}).get('date-parts') or [[year]])[0]
            article.publishDate = '-'.join(str(v).zfill(2) if i else str(v) for i, v in enumerate(parts))
            article.volume = int(item['volume']) if str(item.get('volume', '')).isdigit() else None
            article.issue = int(item['issue']) if str(item.get('issue', '')).isdigit() else 0
            articles.append(article)
        if len(items) < 100:
            return articles
        nextCursor = message.get('next-cursor')
        if not nextCursor or nextCursor == cursor:
            raise ValidationError('Crossref分页未推进，拒绝保存不完整清单。')
        cursor = nextCursor
    raise ValidationError('Crossref超过20页上限，拒绝保存不完整清单。')


def collectSource(sourceId, year, cfg, url='', *, getHtml=None, getJson=None):
    """Return a complete validated batch or raise; caller retains previous review on error."""
    source = sourceById(sourceId)
    if not 1900 <= year <= 2100:
        raise ValidationError('年份应在1900至2100之间。')
    if source['adapter'] == 'index':
        raise ValidationError(f"{source['name']}仅登记官方入口，尚未启用自动拆篇：{source.get('archiveUrl', source['officialUrl'])}")
    http = cfg.get('http', {})
    options = {'userAgent': http.get('userAgent', 'dh-gleaner/overseas'), 'timeout': http.get('timeout', 30),
               'maxRetries': 1, 'retryInterval': 1}
    getHtml = getHtml or fetchHtml
    getJson = getJson or fetchJson
    if source['adapter'] == 'crossref':
        if url:
            raise ValidationError('Crossref来源按ISSN和年份查询，不接受--url。')
        articles = _crossref(source, year, getJson, options)
    else:
        if source['adapter'] == 'anthology' and not url and year != source['conferenceYear']:
            raise ValidationError('该年需使用--url指定已核实的官方会议卷目录，不能沿用其他年份。')
        if source['adapter'] == 'ojs' and not url:
            raise ValidationError('请用--url指定一个官方issue/view目录；不能把档案索引当成一期。')
        target = checkedUrl(url or source['archiveUrl'], source)
        soup = BeautifulSoup(getHtml(target, **options), 'lxml')
        links = []
        if source['adapter'] == 'anthology':
            if not re.fullmatch(r'/volumes/[^/]+/?', urlparse(target).path):
                raise ValidationError('需指定Anthology卷目录，不能指定首页或单篇。')
            title = ' '.join(node.get_text(' ', strip=True) for node in soup.find_all(['h1', 'h2', 'h3']))
            if source['match'].casefold() not in title.casefold() or str(year) not in title:
                raise ValidationError('会议名称或年份不匹配，拒绝采集。')
            for a in soup.select('a[href]'):
                address = urljoin(target.rstrip('/')+'/', a['href'])
                if urlparse(address).path.startswith(urlparse(target).path.rstrip('/')+'/') and address.rstrip('/') != target.rstrip('/') and not urlparse(address).path.endswith(('.pdf', '.bib')):
                    links.append(checkedUrl(address, source))
        else:
            if '/issue/view/' not in urlparse(target).path:
                raise ValidationError('OJS来源必须指定issue/view目录。')
            heading = soup.select_one('h1')
            if not heading or str(year) not in heading.get_text(' ', strip=True):
                raise ValidationError('OJS目录年份不匹配。')
            label = heading.get_text(' ', strip=True)
            source = dict(source, contextLabel=label)
            if not re.search(r'conference|proceedings|workshop', label, re.I):
                source['kind'] = 'journal'
            for a in soup.select('h3.title a[href], .obj_article_summary .title a[href]'):
                links.append(checkedUrl(urljoin(target, a['href']), source))
        links = list(dict.fromkeys(links))
        if not links or len(links) > 500:
            raise ValidationError('未识别单篇文章链接，或链接超过500条；拒绝保存异常目录。')
        articles = [parseCitationPage(getHtml(link, **options), link, source, year) for link in links]
    if not articles:
        raise ValidationError('未获取文章；保留旧筛选清单。')
    seen = set()
    for article in articles:
        key = (article.doi or article.articleUrl or article.title).casefold()
        if key in seen:
            raise ValidationError('来源存在重复条目，拒绝覆盖旧清单。')
        seen.add(key)
        article.capturedAt = datetime.now(timezone.utc).isoformat()
    return source, articles


def runSourceCapture(sourceId, year, cfg, url='', dryRun=False):
    from .service import saveCaptureStatus, savePending
    try:
        source, articles = collectSource(sourceId, year, cfg, url)
    except (ValidationError, RuntimeError, ValueError) as error:
        if not dryRun:
            saveCaptureStatus('failed', str(error))
        raise ValidationError(str(error)) from error
    results = [(source['name'], IssueInfo(year=year), articles)]
    markdown, articles = renderCatalog(results)
    markdown = markdown.replace(f'{year}年第0期', f'{year}年 / 海外来源')
    if not dryRun:
        savePending(markdown, articles, backup=True, captureType='overseas', note=_accessNote(source))
        saveCaptureStatus('success', '海外来源采集完成；完整性仅限指定卷或元数据渠道。', results)
    return markdown, articles


def renderSources(sourceId=''):
    sources = [sourceById(sourceId)] if sourceId else sourceCatalog()['sources']
    lines = ['| ID | 来源 | 采集方式 | 全文 | 机构账号 | 网络 |', '|---|---|---|---|---|---|']
    for source in sources:
        lines.append(f"| {source['id']} | {source['name']} | {source['adapter']} | {source['fulltextAccess']} | {source['institutionRequired']} | 未实测 |")
    lines += ['', 'index=仅登记官方入口；其余为已实现适配器，尚未完成本环境实时网络验证。',
              '公开来源无需机构账号；非OA全文取决于所属机构订阅，可使用机构登录、校园网、图书馆代理或机构VPN。境外网络代理与机构远程访问不同；未实测时不声称必须开VPN。']
    if sourceId:
        lines += ['', json.dumps(sources[0], ensure_ascii=False, indent=2)]
    return '\n'.join(lines)
