"""阶段一：期刊捕获。

支持两种模式：
- 默认模式：抓取各期刊当期目录。
- 目标期次模式：用户指定 year/issue/volume 或目录 URL，抓取指定期次内容。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http_util import FetchBlocked, fetchHtml
from .models import Article, IssueInfo
from .parsers.cnki_cbpt import CnkiCbptParser
from .parsers.founder import FounderParser
from .parsers.generic_html import GenericHtmlParser
from .parsers.journalx import JournalXParser
from .parsers.journy3 import Journy3Parser
from .parsers.magtech import MagtechParser
from .state import StateManager
from .textutil import hasDecodingGarbage, isNavigationTitle

log = logging.getLogger(__name__)
_TZ = timezone(timedelta(hours=8))

#: 站点明确拒绝自动化访问 —— 重试无意义，得换 URL 或转人工
KIND_BLOCKED = "blocked"
#: 临时性故障 —— 稍后重试可能就好了
KIND_FAILED = "failed"

STAGE_LABELS = {
    "resolve": "期次定位失败",
    "fetch": "抓取失败",
    "parse": "解析失败",
    "mismatch": "期次不符",
    "unsupported": "不支持该采集方式",
    "config": "配置缺失",
}


@dataclass
class CaptureFailure:
    """一本刊没抓到东西时，记下卡在哪一步、属于哪一类。

    过去所有异常都被吞成 ``(None, [])`` 只写日志，于是「站点拒绝访问」和「网络抖动」
    在用户眼里一模一样，而批量抓取还会把这种缺失当成一次干净的成功。
    """

    journal: str
    stage: str
    kind: str
    detail: str

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.stage, self.stage)

    def describe(self) -> str:
        return f"《{self.journal}》{self.label}：{self.detail}"

    def toDict(self) -> dict:
        return {"journal": self.journal, "stage": self.stage, "kind": self.kind, "detail": self.detail}


def classifyFetchError(exc: Exception) -> str:
    return KIND_BLOCKED if isinstance(exc, FetchBlocked) else KIND_FAILED


def getParser(parserName: str, journalName: str, httpCfg: dict, journalCfg: Optional[dict] = None):
    """根据 parser 名称实例化对应解析器。"""
    journalCfg = journalCfg or {}
    if parserName == "journy3":
        return Journy3Parser(journalName, httpCfg, baseUrl=journalCfg.get("url", ""))
    if parserName == "cnki_cbpt":
        return CnkiCbptParser(journalName, httpCfg)
    if parserName == "magtech":
        return MagtechParser(
            journalName,
            httpCfg,
            baseUrl=journalCfg.get("url") or journalCfg.get("currentIssueUrl", ""),
            journalCfg=journalCfg,
        )
    if parserName == "founder":
        return FounderParser(journalName, httpCfg, journalCfg=journalCfg)
    if parserName == "journalx":
        return JournalXParser(
            journalName,
            httpCfg,
            baseUrl=journalCfg.get("url") or journalCfg.get("currentIssueUrl", ""),
            journalCfg=journalCfg,
        )
    if parserName == "generic_html":
        return GenericHtmlParser(
            journalName,
            httpCfg,
            baseUrl=journalCfg.get("url") or journalCfg.get("currentIssueUrl", ""),
            options=journalCfg.get("genericRules", {}),
        )
    raise ValueError(f"未知解析器: {parserName}")


def _matchesIssue(issue: IssueInfo, target: Optional[dict]) -> bool:
    if not target:
        return True
    if issue.year != int(target["year"]):
        return False
    if issue.issue != int(target["issue"]):
        return False
    if target.get("volume") is not None and issue.volume != int(target["volume"]):
        return False
    return True


def _currentIssueUrlIfMatches(journalCfg: dict, httpCfg: dict, target: dict) -> Optional[str]:
    userAgent = httpCfg.get("userAgent", "")
    html = fetchHtml(
        journalCfg["currentIssueUrl"],
        userAgent,
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
    )
    parser = getParser(journalCfg["parser"], journalCfg["name"], httpCfg, journalCfg)
    issue, _ = parser.parseCurrentIssue(html)
    if _matchesIssue(issue, target):
        return journalCfg["currentIssueUrl"]
    return None



def _targetVolume(journalCfg: dict, target: dict) -> Optional[int]:
    if target.get("volume") is not None:
        return int(target["volume"])
    baseYear = journalCfg.get("volumeYearBase")
    baseVolume = journalCfg.get("volumeBase")
    if baseYear is None or baseVolume is None:
        return None
    return int(baseVolume) + (int(target["year"]) - int(baseYear))


def _formatHistoryUrl(journalCfg: dict, target: dict) -> str:
    template = journalCfg.get("historyUrlTemplate", "")
    if not template:
        return ""
    volume = _targetVolume(journalCfg, target)
    if "{volume}" in template and volume is None:
        return ""
    return template.format(
        year=int(target["year"]),
        issue=int(target["issue"]),
        volume=volume if volume is not None else "",
    )


def _issueUrlFromHref(baseUrl: str, href: str, target: dict, journalCfg: Optional[dict] = None) -> str:
    if not href:
        return ""
    url = urljoin(baseUrl, href)
    m = re.search(r"/CN/Y(\d{4})(?:/V(\d+))?/I(\d+)", url)
    if not m:
        return ""
    year = int(m.group(1))
    volume = int(m.group(2)) if m.group(2) else None
    issue = int(m.group(3))
    if year != int(target["year"]) or issue != int(target["issue"]):
        return ""
    targetVolume = _targetVolume(journalCfg or {}, target)
    if targetVolume is not None and volume is not None and volume != targetVolume:
        return ""
    return url


def _findMagtechArchiveIssueUrl(archiveUrl: str, html: str, target: dict, journalCfg: dict) -> str:
    soup = BeautifulSoup(html, "lxml")
    matches = []
    for link in soup.find_all("a", href=True):
        matched = _issueUrlFromHref(archiveUrl, link.get("href", ""), target, journalCfg)
        if matched:
            matches.append(matched)
            continue

        text = link.get_text(" ", strip=True)
        row = link.find_parent("tr")
        parent = link.parent.get_text(" ", strip=True) if link.parent else ""
        context = row.get_text(" ", strip=True) if row else f"{parent} {text}"
        yearMatch = re.search(r"(20\d{2})", context)
        volumeMatch = re.search(r"(?:第\s*)?(\d+)\s*卷|Vol\.?\s*(\d+)", context, re.I)
        issueMatch = re.search(r"(?:第\s*)?0*(\d+)\s*期|No\.?\s*0*(\d+)", context, re.I)
        if not (yearMatch and issueMatch):
            continue
        year = int(yearMatch.group(1))
        volume = None
        if volumeMatch:
            volume = int(next(g for g in volumeMatch.groups() if g))
        issue = int(next(g for g in issueMatch.groups() if g))
        if year != int(target["year"]) or issue != int(target["issue"]):
            continue
        targetVolume = _targetVolume(journalCfg, target)
        if targetVolume is not None and volume is not None and volume != targetVolume:
            continue
        href = link.get("href", "")
        if href:
            matches.append(urljoin(archiveUrl, href))

    return matches[0] if matches else ""


def _resolveMagtechIssueUrl(journalCfg: dict, httpCfg: dict, target: dict) -> str:
    currentUrl = _currentIssueUrlIfMatches(journalCfg, httpCfg, target)
    if currentUrl:
        return currentUrl

    archiveError = ""
    archiveUrl = journalCfg.get("archiveUrl") or urljoin(journalCfg["currentIssueUrl"], "../article/showOldVolumn.do")
    try:
        html = fetchHtml(
            archiveUrl,
            httpCfg.get("userAgent", ""),
            timeout=httpCfg.get("timeout", 30),
            maxRetries=httpCfg.get("maxRetries", 3),
            retryInterval=httpCfg.get("retryInterval", 30),
        )
        matched = _findMagtechArchiveIssueUrl(archiveUrl, html, target, journalCfg)
        if matched:
            return matched
    except Exception as e:
        archiveError = f"；过刊页读取失败: {e}"

    guessedUrl = _formatHistoryUrl(journalCfg, target)
    if guessedUrl:
        log.info("《%s》过刊页未定位到目标期次，使用历史期 URL 模板: %s", journalCfg["name"], guessedUrl)
        return guessedUrl

    volume = _targetVolume(journalCfg, target)
    volumeHint = f" 第{volume}卷" if volume is not None else ""
    manualHint = ""
    template = journalCfg.get("historyUrlTemplate", "")
    if template:
        possible = _formatHistoryUrl(journalCfg, {**target, "volume": volume} if volume is not None else target)
        if possible:
            manualHint = f"。可尝试 --url {possible}"
        elif "{volume}" in template:
            manualHint = (
                "。该刊的 historyUrlTemplate 需要卷号，但配置里缺 volumeYearBase/volumeBase，"
                "无法推算卷号；请在官网找到该期目录页后用 --url 指定"
            )
    raise RuntimeError(
        f"未在《{journalCfg['name']}》Magtech 过刊页找到 {target['year']}年{volumeHint} 第{target['issue']}期{archiveError}{manualHint}"
    )

def _resolveJourny3IssueUrl(journalCfg: dict, httpCfg: dict, target: dict) -> str:
    currentUrl = _currentIssueUrlIfMatches(journalCfg, httpCfg, target)
    if currentUrl:
        return currentUrl

    archiveUrl = journalCfg.get("archiveUrl") or urljoin(journalCfg["currentIssueUrl"], "../article/showOldVolumn.do")
    html = fetchHtml(
        archiveUrl,
        httpCfg.get("userAgent", ""),
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
    )
    soup = BeautifulSoup(html, "lxml")
    matches = []
    for link in soup.find_all("a", href=re.compile(r"volumn_\d+\.shtml")):
        text = link.get_text(" ", strip=True)
        row = link.find_parent("tr")
        context = row.get_text(" ", strip=True) if row else link.parent.get_text(" ", strip=True)
        yearMatch = re.search(r"(20\d{2})", context)
        volumeMatch = re.search(r"Vol\.?\s*(\d+)", context, re.I)
        issueMatch = re.search(r"No\.?\s*(\d+)", text, re.I)
        if not issueMatch:
            allIssues = re.findall(r"No\.?\s*(\d+)", context, re.I)
            if len(allIssues) == 1:
                issueMatch = re.search(r"No\.?\s*(\d+)", context, re.I)
        if not (yearMatch and issueMatch):
            continue
        year = int(yearMatch.group(1))
        volume = int(volumeMatch.group(1)) if volumeMatch else None
        issue = int(issueMatch.group(1))
        if year != int(target["year"]) or issue != int(target["issue"]):
            continue
        if target.get("volume") is not None and volume != int(target["volume"]):
            continue
        matches.append(urljoin(archiveUrl, link.get("href", "")))

    if matches:
        return matches[0]
    volumeHint = f" 第{target['volume']}卷" if target.get("volume") is not None else ""
    raise RuntimeError(f"未在《{journalCfg['name']}》过刊页找到 {target['year']}年{volumeHint} 第{target['issue']}期")


def _resolveCnkiIssueUrl(journalCfg: dict, httpCfg: dict, target: dict) -> str:
    currentUrl = _currentIssueUrlIfMatches(journalCfg, httpCfg, target)
    if currentUrl:
        return currentUrl
    raise RuntimeError(
        f"《{journalCfg['name']}》CNKI 采编平台历史期次目录需要验证码，当前只支持抓取公开首页显示的当期期次；"
        "如你有可直接访问的目录页，请使用 --journal 数字人文 --url 目录页URL。"
    )


def resolveIssueUrl(journalCfg: dict, httpCfg: dict, target: Optional[dict] = None, explicitUrl: str = "") -> str:
    """根据用户指定的目标期次解析目录页 URL。"""
    if explicitUrl:
        return explicitUrl
    if not target:
        return journalCfg["currentIssueUrl"]
    parserName = journalCfg["parser"]
    if parserName == "journy3":
        return _resolveJourny3IssueUrl(journalCfg, httpCfg, target)
    if parserName == "magtech":
        return _resolveMagtechIssueUrl(journalCfg, httpCfg, target)
    if parserName == "cnki_cbpt":
        return _resolveCnkiIssueUrl(journalCfg, httpCfg, target)
    if parserName == "generic_html":
        if journalCfg.get("currentIssueUrl"):
            return journalCfg["currentIssueUrl"]
        raise RuntimeError(f"《{journalCfg['name']}》暂无稳定公开目录页，请使用 --url 提供可访问的目录页URL。")
    raise ValueError(f"未知解析器: {parserName}")




def assessCaptureQuality(issue: Optional[IssueInfo], articles: List[Article], captureType: str = "issue") -> tuple[str, str]:
    """判断抓取结果是否像有效文章清单；suspect 不应覆盖旧清单。"""
    if not articles:
        return "failed", "未捕获到文章"
    if captureType == "issue" and issue and issue.year == 0 and issue.issue == 0:
        return "suspect", "期次解析为 0年第0期，疑似抓到非目标页面"
    badCount = sum(1 for article in articles if isNavigationTitle(article.title))
    badRatio = badCount / max(len(articles), 1)
    if badRatio >= 0.25:
        return "suspect", f"疑似导航/广告标题占比过高: {badCount}/{len(articles)}"
    garbled = sum(1 for article in articles if hasDecodingGarbage(article.title, article.abstract))
    if garbled:
        return "suspect", f"标题/摘要含解码替换符 U+FFFD，疑似编码判断出错: {garbled}/{len(articles)}"
    uniqueTitles = {re.sub(r"\s+", "", article.title or "") for article in articles}
    if len(articles) >= 5 and len(uniqueTitles) / len(articles) < 0.6:
        return "suspect", "重复标题比例过高，疑似误抓页面"
    return "success", ""


def assessBatchQuality(
    results: List[Tuple[str, Optional[IssueInfo], List[Article]]],
    failures: List[CaptureFailure],
    captureType: str = "issue",
) -> tuple[str, str]:
    """逐刊判定整批抓取的质量。

    不能用聚合后的文章列表判：13 本里 12 本失败、1 本抓到 6 篇，聚合看仍是
    「有文章、标题干净」，于是判 success 并覆盖掉上一次完整的待筛清单。
    这里改成每本刊单独过一遍 ``assessCaptureQuality``，任一刊异常整批就不算成功。

    「合法的空」不算异常：dedupe 命中已处理期次、harvest 的 dhOnly 筛完无命中，
    这两种情况不会记入 ``failures``，因此不会拖累整批判定。
    """
    if not results:
        return "failed", "没有任何期刊进入本次抓取"

    if failures:
        detail = "；".join(f.describe() for f in failures)
        if all(not arts for _, _, arts in results):
            return "failed", detail
        return "suspect", f"{len(failures)}/{len(results)} 本刊抓取异常，未覆盖旧清单：{detail}"

    reasons: List[str] = []
    for name, issue, articles in results:
        # 空列表且无 failure 记录 = 合法的空（dedupe 已处理 / dhOnly 无命中），不算异常
        if not articles:
            continue
        quality, reason = assessCaptureQuality(issue, articles, captureType)
        if quality != "success":
            reasons.append(f"《{name}》{reason}")

    if reasons:
        return "suspect", "；".join(reasons)
    if all(not articles for _, _, articles in results):
        return "failed", "各刊均无新文章（可能已处理过，或筛完无命中）"
    return "success", ""


def _channelSource(journalCfg: dict, channelName: str) -> dict:
    for source in journalCfg.get("channelSources", []):
        names = [source.get("channel", "")] + source.get("aliases", [])
        if channelName in names:
            return source
    return {}


def captureChannel(
    journalCfg: dict,
    httpCfg: dict,
    state: StateManager,
    channelName: str,
    explicitUrl: str = "",
    dedupe: bool = False,
) -> Tuple[Optional[IssueInfo], List[Article], Optional[CaptureFailure]]:
    """抓取栏目型清单；栏目可跨多个期次，每篇文章保留自己的年卷期。"""
    name = journalCfg["name"]
    parserName = journalCfg["parser"]
    if parserName != "magtech":
        detail = f"当前解析器为 {parserName}，暂不支持 capture-channel"
        log.error("《%s》%s", name, detail)
        return None, [], CaptureFailure(name, "unsupported", KIND_FAILED, detail)

    source = _channelSource(journalCfg, channelName)
    url = explicitUrl or source.get("url", "")
    if not url:
        detail = f"未配置栏目《{channelName}》的 URL，请使用 --url 手动指定"
        log.error("《%s》%s", name, detail)
        return None, [], CaptureFailure(name, "config", KIND_FAILED, detail)

    userAgent = httpCfg.get("userAgent", "")
    parser = getParser(parserName, name, httpCfg, journalCfg)
    pages = [url]
    pageHtml = {}
    try:
        firstHtml = fetchHtml(url, userAgent, timeout=httpCfg.get("timeout", 30), maxRetries=httpCfg.get("maxRetries", 3), retryInterval=httpCfg.get("retryInterval", 30))
        pageHtml[url] = firstHtml
        pages = parser.discoverChannelPageUrls(firstHtml, url)
    except Exception as e:
        log.error("《%s》栏目《%s》首页抓取失败: %s", name, channelName, e)
        return None, [], CaptureFailure(name, "fetch", classifyFetchError(e), f"栏目《{channelName}》首页抓取失败：{e}")

    allArticles: List[Article] = []
    issue = IssueInfo(year=0, volume=None, issue=0)
    seen = set()
    failedPages: List[str] = []
    pageDelay = float(httpCfg.get("harvestDelay", 0.6))
    for index, pageUrl in enumerate(pages):
        # 栏目分页全是同一台主机，逐页之间要限速；首页已经抓过所以从第二页起才等
        if index and pageDelay > 0:
            time.sleep(pageDelay)
        try:
            html = pageHtml.get(pageUrl) or fetchHtml(pageUrl, userAgent, timeout=httpCfg.get("timeout", 30), maxRetries=httpCfg.get("maxRetries", 3), retryInterval=httpCfg.get("retryInterval", 30))
            pageIssue, articles = parser.parseChannelPage(html, channelName=source.get("channel", channelName))
            issue = pageIssue or issue
            for article in articles:
                key = article.articleKey()
                if key in seen:
                    continue
                seen.add(key)
                if dedupe and state.isArticleProcessed(name, key):
                    continue
                allArticles.append(article)
        except Exception as e:
            # 单页失败会让整栏清单静默缺一截，因此必须记下来而不是只写日志
            log.warning("《%s》栏目《%s》分页抓取失败: %s — %s", name, channelName, pageUrl, e)
            failedPages.append(pageUrl)

    state.updateLastCheck(name)
    nowIso = datetime.now(_TZ).isoformat(timespec="seconds")
    for article in allArticles:
        article.capturedAt = nowIso
    log.info("《%s》栏目《%s》捕获完成: %d 页, %d 篇", name, channelName, len(pages), len(allArticles))

    problems: List[str] = []
    if failedPages:
        problems.append(
            f"{len(failedPages)}/{len(pages)} 页抓取失败，清单可能不完整：{', '.join(failedPages[:3])}"
        )
    pageCap = int(getattr(parser, "maxChannelPages", 0) or 0)
    if pageCap and len(pages) >= pageCap:
        problems.append(
            f"分页达到上限 {pageCap} 页，只抓到这么多；如需全量请调大该刊配置的 maxChannelPages"
        )
        log.warning("《%s》栏目《%s》%s", name, channelName, problems[-1])

    failure = None
    if problems:
        failure = CaptureFailure(name, "fetch", KIND_FAILED, f"栏目《{channelName}》" + "；".join(problems))
    return issue, allArticles, failure

def captureJournal(
    journalCfg: dict,
    httpCfg: dict,
    state: StateManager,
    target: Optional[dict] = None,
    explicitUrl: str = "",
    dedupe: bool = True,
) -> Tuple[Optional[IssueInfo], List[Article], Optional[CaptureFailure]]:
    """捕获单个期刊的目录文章。

    第三个返回值是失败记录；``None`` 表示没有失败。文章列表为空但失败记录也为
    ``None``，说明这是合法的空（dedupe 命中已处理期次），不该算异常。
    """
    name = journalCfg["name"]
    parserName = journalCfg["parser"]
    userAgent = httpCfg.get("userAgent", "")

    try:
        url = resolveIssueUrl(journalCfg, httpCfg, target=target, explicitUrl=explicitUrl)
    except Exception as e:
        log.error("《%s》目标期次解析失败: %s", name, e)
        return None, [], CaptureFailure(name, "resolve", classifyFetchError(e), str(e))

    log.info("开始捕获《%s》: %s", name, url)

    try:
        html = fetchHtml(
            url,
            userAgent,
            timeout=httpCfg.get("timeout", 30),
            maxRetries=httpCfg.get("maxRetries", 3),
            retryInterval=httpCfg.get("retryInterval", 30),
        )
    except Exception as e:
        log.error("《%s》抓取失败: %s", name, e)
        return None, [], CaptureFailure(name, "fetch", classifyFetchError(e), str(e))

    parser = getParser(parserName, name, httpCfg, journalCfg)
    try:
        issue, articles = parser.parseCurrentIssue(html)
    except Exception as e:
        log.error("《%s》解析失败: %s", name, e)
        return None, [], CaptureFailure(name, "parse", KIND_FAILED, str(e))

    if target and not _matchesIssue(issue, target):
        detail = f"抓到的是 {issue.label()}，不是指定的 {target['year']}年第{target['issue']}期"
        log.error("《%s》%s", name, detail)
        return issue, [], CaptureFailure(name, "mismatch", KIND_FAILED, detail)

    state.updateLastCheck(name)

    if dedupe and issue.year and state.isIssueProcessed(name, issue):
        log.info("《%s》%s 已处理过，无新文章", name, issue.label())
        return issue, [], None

    if dedupe:
        resultArticles = [
            article for article in articles
            if not state.isArticleProcessed(name, article.articleKey())
        ]
    else:
        resultArticles = list(articles)

    if resultArticles:
        try:
            resultArticles = parser.fetchAbstracts(resultArticles)
        except Exception as e:
            log.warning("《%s》摘要补全失败: %s", name, e)

    nowIso = datetime.now(_TZ).isoformat(timespec="seconds")
    for article in resultArticles:
        article.capturedAt = nowIso

    log.info("《%s》捕获完成: %s, 文章 %d 篇", name, issue.label(), len(resultArticles))
    return issue, resultArticles, None


def captureAll(
    journalsCfg: list,
    httpCfg: dict,
    state: StateManager,
    force: bool = False,
    target: Optional[dict] = None,
    journalName: str = "",
    explicitUrl: str = "",
    dedupe: Optional[bool] = None,
) -> Tuple[List[Tuple[str, Optional[IssueInfo], List[Article]]], List[CaptureFailure]]:
    """捕获所有或指定期刊，返回 ``(结果三元组列表, 失败记录列表)``。"""
    results = []
    failures: List[CaptureFailure] = []
    manualTarget = bool(target or explicitUrl)
    useDedupe = (not manualTarget) if dedupe is None else dedupe
    for journalCfg in journalsCfg:
        name = journalCfg["name"]
        if journalName and name != journalName:
            continue
        if not journalName and journalCfg.get("harvestOnly"):
            log.info("《%s》是散篇 harvest 期刊，capture 全量轮转跳过；请用 harvest 命令按年采集", name)
            continue
        if explicitUrl and not journalName:
            detail = "使用 --url 时必须同时指定 --journal"
            log.error(detail)
            results.append((name, None, []))
            failures.append(CaptureFailure(name, "config", KIND_FAILED, detail))
            continue
        issue, articles, failure = captureJournal(
            journalCfg,
            httpCfg,
            state,
            target=target,
            explicitUrl=explicitUrl if (not journalName or name == journalName) else "",
            dedupe=useDedupe,
        )
        results.append((name, issue, articles))
        if failure:
            failures.append(failure)
    return results, failures
