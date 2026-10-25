"""发现层 — 回答「这本刊现在最新的已知期次是哪一期，以及抓不抓得到」。

capture 的「最新」等于「配置里 currentIssueUrl 此刻显示的期次」。图情刊的真实新鲜度是
分层的（公众号目录 > 期刊自建系统 > 聚合站），所以单一入口必然滞后，而且滞后的结果
在质量闸门里长得跟「没有新刊」一模一样。本层把每刊的枚举源显式写成 `discovery.sources`，
逐个问「你知道的最新一期是几期」，再按 tier 汇总出最新已知期次与各源落后几期。

tier 约定：**1 = 最早公告**（常常只有题录、没有逐篇页），**2 = 官方逐篇页**，
**3 = 聚合/镜像站**（最滞后，但往往是唯一有摘要的源）。

红线与 capture 相同：只访问公开页面与公开接口；401/403/412 由 `fetchHtml`/`fetchJson`
立即抛 `FetchBlocked`，不绕过、不重试；每刊每次 discover 最多几档请求，不做轮询。

发现层只要「最新一期」这个事实，不用于逐期定位：`volumn_N.shtml` 的 N 是 CMS 内部 id，
跨刊、跨年都不单调（实测情报科学 id 1275=No.2 而 id 1273=No.5），因此一律按
(年, 期) 取最大值，绝不按 id 或 DOM 序号推断期次。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http_util import FetchBlocked, fetchHtml, fetchJson
from .models import IssueInfo

log = logging.getLogger(__name__)
_TZ = timezone(timedelta(hours=8))

#: 年度块头 / 行内标签里的期次号上限。超过它的是「总期号」系列（实测图书馆杂志
#: 2026 年度块里 No.1–No.8 与 No.413–No.416 并存），拿来当期刊号会算出第 416 期。
MAX_ISSUE_PER_YEAR = 12

_YEAR_RE = re.compile(r"(20\d{2})\s*年?")
_VOLUME_RE = re.compile(r"(?:Vol\.?\s*|第\s*)(\d{1,2})\s*卷?")
_ISSUE_RE = re.compile(r"(?:No\.?\s*(\d{1,3})\s*期?|第\s*(\d{1,3})\s*期)", re.I)
_CNKI_ISSUE_RE = re.compile(r"(20\d{2})\s*年\s*0*(\d{1,2})\s*期")
#: 「2025年第4期」「2026 年第 3 辑」都算；单位必须出现，否则「2025年4月」会被读成第4期。
_LABEL_ISSUE_RE = re.compile(r"(\d{4})\s*年\s*(?:第)?\s*0*(\d{1,2})\s*[期辑]")


@dataclass
class IssueRef:
    """某来源宣告的一个期次。"""

    year: int
    issue: int
    volume: Optional[int] = None
    url: str = ""
    sourceId: str = ""
    tier: int = 2
    evidence: str = ""

    def issueInfo(self) -> IssueInfo:
        return IssueInfo(year=self.year, volume=self.volume, issue=self.issue)

    def label(self) -> str:
        if not self.issue:
            return f"{self.year}年（期次未标注）"
        return self.issueInfo().label()

    def sortKey(self) -> tuple:
        return (self.year, self.issue, self.volume or 0)

    def toDict(self) -> dict:
        return {
            "year": self.year,
            "issue": self.issue,
            "volume": self.volume,
            "label": self.label(),
            "url": self.url,
            "sourceId": self.sourceId,
            "tier": self.tier,
            "evidence": self.evidence,
        }


@dataclass
class SourceResult:
    """单个发现源的探测结果。"""

    sourceId: str
    kind: str
    tier: int
    status: str  # ok / empty / blocked / failed / manual
    latest: Optional[IssueRef] = None
    detail: str = ""
    note: str = ""
    hints: List[str] = field(default_factory=list)

    def gapTo(self, frontier: Optional[IssueRef], issuesPerYear: int) -> Optional[int]:
        """落后最新已知期次几期；跨年少算不如明确按 issuesPerYear 折算。"""
        if not frontier or not self.latest:
            return None
        if not frontier.issue or not self.latest.issue:
            return None
        return (
            (frontier.year - self.latest.year) * issuesPerYear
            + (frontier.issue - self.latest.issue)
        )

    def toDict(self, frontier: Optional[IssueRef], issuesPerYear: int) -> dict:
        gap = self.gapTo(frontier, issuesPerYear)
        return {
            "sourceId": self.sourceId,
            "kind": self.kind,
            "tier": self.tier,
            "status": self.status,
            "latest": self.latest.toDict() if self.latest else None,
            "lagIssues": gap,
            "detail": self.detail,
            "note": self.note,
            "hints": self.hints,
        }


@dataclass
class JournalDiscovery:
    journal: str
    issuesPerYear: int = MAX_ISSUE_PER_YEAR
    sources: List[SourceResult] = field(default_factory=list)
    frontier: Optional[IssueRef] = None
    official: Optional[IssueRef] = None
    stateKnown: Optional[dict] = None
    nextAction: str = ""
    harvestOnly: bool = False
    hints: List[str] = field(default_factory=list)

    def toDict(self) -> dict:
        return {
            "journal": self.journal,
            "frontier": self.frontier.toDict() if self.frontier else None,
            "official": self.official.toDict() if self.official else None,
            "stateKnown": self.stateKnown,
            "nextAction": self.nextAction,
            "harvestOnly": self.harvestOnly,
            "hints": self.hints,
            "sources": [s.toDict(self.frontier, self.issuesPerYear) for s in self.sources],
        }


def _sourcesOf(journalCfg: dict) -> List[dict]:
    return list((journalCfg.get("discovery") or {}).get("sources") or [])


def _probe(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> SourceResult:
    kind = spec.get("kind", "")
    sourceId = spec.get("id") or kind
    tier = int(spec.get("tier", 2))
    result = SourceResult(sourceId=sourceId, kind=kind, tier=tier, status="empty", note=spec.get("note", ""))
    # hints：机器到不了这一步时，人还能走哪几条路。写在配置里，代码不猜站点的名字。
    result.hints = [str(h) for h in spec.get("hints") or []]
    enumerator = ENUMERATORS.get(kind)
    if enumerator is None:
        result.status = "failed"
        result.detail = f"未知发现源类型: {kind}"
        return result
    try:
        refs = enumerator(spec, journalCfg, httpCfg, state, today)
    except ManualSourceNeeded as e:
        result.status = "manual"
        result.detail = str(e)
        return result
    except FetchBlocked as e:
        result.status = "blocked"
        result.detail = str(e)
        return result
    except Exception as e:
        result.status = "failed"
        result.detail = f"{type(e).__name__}: {e}"
        return result
    if not refs:
        result.detail = "该源未宣告任何期次"
        return result
    result.latest = max(refs, key=lambda ref: ref.sortKey())
    result.status = "ok"
    result.detail = f"{len(refs)} 个期次, 最新 {result.latest.label()}"
    return result


def _nextAction(journalCfg: dict, frontier: Optional[IssueRef], results: List[SourceResult]) -> str:
    if frontier is None:
        return "人工确认该刊当前是否有新刊：各发现源均未宣告期次"
    spec = next(
        (s for s in _sourcesOf(journalCfg) if (s.get("id") or s.get("kind")) == frontier.sourceId),
        {},
    )
    action = spec.get("fetch") or ("harvest" if journalCfg.get("harvestOnly") else "capture")
    template = FETCH_ACTIONS.get(action, FETCH_ACTIONS["capture"])
    channel = spec.get("channel") or next(
        (c.get("channel") for c in journalCfg.get("channelSources") or []), ""
    )
    return "dhgleaner " + template.format(
        journal=journalCfg.get("name", ""),
        year=frontier.year,
        issue=frontier.issue,
        url=frontier.url or "（目录页 URL）",
        channel=channel or "栏目名",
    )


def discoverJournal(
    journalCfg: dict,
    httpCfg: dict,
    *,
    state=None,
    today: Optional[date] = None,
    record: bool = True,
) -> JournalDiscovery:
    """按 tier 从低到高探测该刊的全部发现源，汇出「最新已知期次」。"""
    today = today or datetime.now(_TZ).date()
    name = journalCfg["name"]
    discoveryCfg = journalCfg.get("discovery") or {}
    issuesPerYear = int(discoveryCfg.get("issuesPerYear") or MAX_ISSUE_PER_YEAR)
    discovery = JournalDiscovery(
        journal=name,
        issuesPerYear=issuesPerYear,
        harvestOnly=bool(journalCfg.get("harvestOnly")),
        stateKnown=state.getLatestKnown(name) if state else None,
        hints=[str(h) for h in discoveryCfg.get("hints") or []],
    )
    specs = sorted(_sourcesOf(journalCfg), key=lambda spec: int(spec.get("tier", 2)))
    refs: List[IssueRef] = []
    for spec in specs:
        result = _probe(spec, journalCfg, httpCfg, state, today)
        discovery.sources.append(result)
        if result.latest:
            refs.append(result.latest)
        log.info(
            "《%s》发现源 %s(tier%s) -> %s %s",
            name, result.sourceId, result.tier, result.status, result.detail,
        )

    if refs:
        # 只有标了期次的才能当「最新一期」；未标期次的（如 WordPress 最新推文）
        # 只是「站上有今年内容」的信号，留在各源明细里，不参与排序。
        numbered = [ref for ref in refs if ref.issue]
        if numbered:
            discovery.frontier = max(numbered, key=lambda ref: ref.sortKey())
            officialIds = {(s.get("id") or s.get("kind")) for s in specs if s.get("official")}
            candidates = [ref for ref in numbered if ref.sourceId in officialIds] or [
                ref for ref in numbered if ref.tier >= 2
            ]
            if candidates:
                discovery.official = max(candidates, key=lambda ref: ref.sortKey())
    discovery.nextAction = _nextAction(journalCfg, discovery.frontier, discovery.sources)

    if record and state is not None and discovery.frontier:
        state.recordLatestKnown(name, discovery.frontier.toDict())
    return discovery


def discoverAll(
    cfg: dict,
    *,
    journalName: str = "",
    state=None,
    today: Optional[date] = None,
    record: bool = True,
) -> List[JournalDiscovery]:
    """探测配置中的全部（或指定）期刊。journalName 为空串表示全部。"""
    journals = cfg.get("journals", [])
    discoveries = []
    for journalCfg in journals:
        if journalName and journalCfg["name"] != journalName:
            continue
        specs = _sourcesOf(journalCfg)
        if not specs:
            discoveries.append(
                JournalDiscovery(
                    journal=journalCfg["name"],
                    nextAction="该刊未配置 discovery.sources；capture 的「最新」仍等于 currentIssueUrl 显示的期次",
                )
            )
            continue
        discoveries.append(
            discoverJournal(
                journalCfg,
                cfg.get("http", {}),
                state=state,
                today=today,
                record=record,
            )
        )
    return discoveries


def renderDiscoveries(discoveries: List[JournalDiscovery]) -> str:
    """把发现结果渲染成人读的清单（CLI 用；MCP 直接吃 toDict）。"""
    lines: List[str] = []
    for item in discoveries:
        lines.append(f"\n《{item.journal}》")
        if not item.sources:
            lines.append(f"  {item.nextAction}")
            for hint in item.hints:
                lines.append(f"    · {hint}")
            continue
        frontier = item.frontier.label() if item.frontier else "未宣告"
        source = item.frontier.sourceId if item.frontier else ""
        tier = f"tier{item.frontier.tier}" if item.frontier else ""
        lines.append(f"  最新已知期次  {frontier}   ← {source} {tier}")
        if item.official and item.frontier and item.official.sortKey() < item.frontier.sortKey():
            gap = (item.frontier.year - item.official.year) * item.issuesPerYear + (
                item.frontier.issue - item.official.issue
            )
            lines.append(f"  逐篇官方页    {item.official.label()}   ← 比最新公告落后 {gap} 期")
        for result in item.sources:
            mark = {"ok": "✓", "blocked": "⛔", "failed": "✗", "empty": "·", "manual": "✍"}.get(
                result.status, "?"
            )
            reported = result.latest.label() if result.latest else "—"
            gap = result.gapTo(item.frontier, item.issuesPerYear)
            lag = f"（落后 {gap} 期）" if gap else ""
            lines.append(f"    {mark} tier{result.tier} {result.sourceId}: {reported}{lag} {result.detail}")
            if result.status in ("manual", "blocked", "failed", "empty") and result.hints:
                for hint in result.hints:
                    lines.append(f"        · {hint}")
        if item.stateKnown:
            known = item.stateKnown.get("label") or ""
            if item.frontier and item.stateKnown.get("year"):
                stale = (item.frontier.year, item.frontier.issue) > (
                    item.stateKnown.get("year"),
                    item.stateKnown.get("issue"),
                )
                lines.append(f"    上次记录      {known}{'（本次更新）' if stale else '（无变化）'}")
        lines.append(f"  下一步：{item.nextAction}")
        needsHuman = item.frontier is None or any(
            r.status in ("manual", "blocked", "failed") for r in item.sources
        )
        if needsHuman:
            for hint in item.hints:
                lines.append(f"    · {hint}")
    return "\n".join(lines).lstrip()


__all__ = [
    "ENUMERATORS",
    "IssueRef",
    "JournalDiscovery",
    "ManualSourceNeeded",
    "SourceResult",
    "discoverAll",
    "discoverJournal",
    "renderDiscoveries",
]



# ---------------------------------------------------------------------------
# 各发现源的实现
# ---------------------------------------------------------------------------

def _fetchHtml(spec: dict, url: str, httpCfg: dict) -> str:
    return fetchHtml(
        url,
        httpCfg.get("userAgent", ""),
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
    )


def _yearVolume(text: str) -> tuple[int, Optional[int]]:
    yearMatch = _YEAR_RE.search(text)
    volumeMatch = _VOLUME_RE.search(text)
    year = int(yearMatch.group(1)) if yearMatch else 0
    volume = int(volumeMatch.group(1)) if volumeMatch else None
    return year, volume


def _issueFrom(candidates: List[str]) -> int:
    """按优先级取第一个合法的年度期号；>12 的一律当总期号跳过。

    「第N卷」不能当期号，所以中文形式强制要求跟「期」；No.N 本身已带期次语义，可省略。
    """
    for text in candidates:
        for match in _ISSUE_RE.finditer(text or ""):
            value = int(match.group(1) or match.group(2))
            if 1 <= value <= MAX_ISSUE_PER_YEAR:
                return value
    return 0


def _blockYearVolume(anchor) -> tuple[int, Optional[int], str]:
    """条目往前找最近的「年 / 卷」块头。

    年+卷在块头、期号在行内 `<a>`，两者不在同一节点；直接取 `<a>` 自己的父节点会
    拿不到年份（实测五本 magtech/journy3 刊皆如此）。
    """
    node = anchor
    for _ in range(10):
        node = node.find_previous(
            ["h1", "h2", "h3", "h4", "h5", "b", "strong", "caption", "th", "td", "tr", "li", "div", "option", "select"]
        )
        if node is None:
            break
        text = node.get_text(" ", strip=True)
        year, volume = _yearVolume(text)
        if year:
            return year, volume, text[:60]
    return 0, None, ""


def _enumArchiveVolumn(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """过刊索引页：年度块头 + `volumn_N.shtml` 行，一次请求拿到全部 (年, 卷, 期)。"""
    url = spec["url"]
    soup = BeautifulSoup(_fetchHtml(spec, url, httpCfg), "lxml")
    refs: List[IssueRef] = []
    for anchor in soup.find_all("a", href=re.compile(r"volumn_(\d+)\.shtml")):
        row = anchor.find_parent("tr") or anchor.find_parent("li") or anchor
        labelText = anchor.get_text(" ", strip=True)
        issue = _issueFrom([labelText, row.get_text(" ", strip=True)])
        year, volume, evidence = _blockYearVolume(anchor)
        if not issue:
            issue = _issueFrom([evidence])
        if not (year and issue):
            continue
        refs.append(
            IssueRef(
                year=year,
                issue=issue,
                volume=volume,
                url=urljoin(url, anchor.get("href", "")),
                sourceId=spec.get("id", "archive"),
                tier=int(spec.get("tier", 2)),
                evidence=f"{evidence} / {labelText or '（无标签）'}",
            )
        )
    return refs


def _enumArchiveYvi(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """过刊索引页（另一种皮肤）：`/CN/Y{年}/V{卷}/I{期}` 直链。"""
    url = spec["url"]
    soup = BeautifulSoup(_fetchHtml(spec, url, httpCfg), "lxml")
    refs: List[IssueRef] = []
    for anchor in soup.find_all("a", href=re.compile(r"/CN/Y\d{4}(?:/V\d+)?/I\d+")):
        href = anchor.get("href", "")
        parsed = re.search(r"/CN/Y(\d{4})(?:/V(\d+))?/I(\d+)", href)
        if not parsed:
            continue
        refs.append(
            IssueRef(
                year=int(parsed.group(1)),
                issue=int(parsed.group(3)),
                volume=int(parsed.group(2)) if parsed.group(2) else None,
                url=urljoin(url, href),
                sourceId=spec.get("id", "archive"),
                tier=int(spec.get("tier", 2)),
                evidence=href,
            )
        )
    return refs


def _enumCnkiCurrent(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """CNKI 采编平台首页：只宣告它当前的那一期。

    cbpt 域名错配不会 404，而是静默渲染**另一本刊**的首页（实测 mid=GJTS 返回
    《国际经贸探索》2026年09期），所以必须按刊名校验页面归属，宁可 failed 不可假 frontier。
    """
    url = spec["url"]
    text = BeautifulSoup(_fetchHtml(spec, url, httpCfg), "lxml").get_text(" ", strip=True)
    required = spec.get("requiredPageText") or ([journalCfg["name"]] if journalCfg.get("name") else [])
    missing = [token for token in required if token not in text]
    if missing:
        raise ValueError(f"页面缺少刊名标识 {missing}，疑似 cbpt 域名错配到别的期刊")
    match = _CNKI_ISSUE_RE.search(text)
    if not match:
        return []
    return [
        IssueRef(
            year=int(match.group(1)),
            issue=int(match.group(2)),
            url=url,
            sourceId=spec.get("id", "cnki-current"),
            tier=int(spec.get("tier", 2)),
            evidence=match.group(0),
        )
    ]


def _enumFounderTree(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """方正发布平台 getPeriodTree：年 → 期 → periodId，公开 JSON。"""
    siteId = journalCfg.get("siteId") or spec.get("siteId")
    if not siteId:
        raise ValueError("缺少 siteId，无法调用方正期次树接口")
    apiBase = (spec.get("apiBase") or "https://www.publish.founderss.cn").rstrip("/")
    data = fetchJson(
        f"{apiBase}/rc-pub/front/front-period/getPeriodTree?siteId={siteId}",
        httpCfg.get("userAgent", ""),
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
        referer=journalCfg.get("referer", ""),
    )
    refs: List[IssueRef] = []
    for group in data.get("data") or []:
        for yearGroup in group.get("periods") or []:
            year = yearGroup.get("year")
            for period in yearGroup.get("periods") or []:
                issue = period.get("issue")
                if not year or issue in (None, ""):
                    continue
                try:
                    issueInt = int(issue)
                except (TypeError, ValueError):
                    continue
                refs.append(
                    IssueRef(
                        year=int(year),
                        issue=issueInt,
                        volume=period.get("volume") if str(period.get("volume") or "").isdigit() else None,
                        url=spec.get("url") or journalCfg.get("url", ""),
                        sourceId=spec.get("id", "founder-tree"),
                        tier=int(spec.get("tier", 2)),
                        evidence=f"periodId={period.get('id')}",
                    )
                )
    return refs


def _expectedQuarter(today: date, issuesPerYear: int, maxQuarter: int) -> int:
    """按该刊年发文量折算「本月理应有第几档」，作为往下扫的起点。

    双月刊用 12 起扫会整段跨过年中真正的最新一期（实测中国图书馆学报 2026 年
    第4期之后 Q5/Q6 都还没上线），白扫也不报错，只会报「未宣告」。
    """
    return max(1, min(maxQuarter, math.ceil(today.month / 12 * issuesPerYear)))


def _enumJournalxQuarters(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """JournalX .NET：没有「最新一期」页，只能从预期档号往下扫到第一个有正文的档。"""
    base = spec["url"].rstrip("/")
    maxQuarter = int(journalCfg.get("maxQuarter") or spec.get("maxQuarter") or 12)
    issuesPerYear = int(
        spec.get("issuesPerYear")
        or (journalCfg.get("discovery") or {}).get("issuesPerYear")
        or maxQuarter
    )
    expected = _expectedQuarter(today, issuesPerYear, maxQuarter)
    start = int(spec.get("startQuarter") or expected)
    steps = int(spec.get("maxScanSteps", 4))
    for quarter in range(start, max(0, start - steps - 1), -1):
        url = f"{base}/issue_list.aspx?year_id={today.year}&quarter_id={quarter}"
        soup = BeautifulSoup(_fetchHtml(spec, url, httpCfg), "lxml")
        rows = len(soup.find_all("a", href=re.compile("view_abstract|showabstract", re.I)))
        if rows:
            return [
                IssueRef(
                    year=today.year,
                    issue=quarter,
                    url=url,
                    sourceId=spec.get("id", "journalx"),
                    tier=int(spec.get("tier", 2)),
                    evidence=f"{rows} 篇",
                )
            ]
        log.debug("JournalX %d年第%d档无正文，继续往下扫", today.year, quarter)
    return []


def _enumWordpressCategories(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """WordPress 分类接口：一个分类 = 一期，分类名里带「2025年第4期」。"""
    data = fetchJson(
        spec["url"],
        httpCfg.get("userAgent", ""),
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
    )
    if not isinstance(data, list):
        return []
    refs: List[IssueRef] = []
    for category in data:
        name = str(category.get("name") or "")
        match = _LABEL_ISSUE_RE.search(name)
        if not match:
            continue
        refs.append(
            IssueRef(
                year=int(match.group(1)),
                issue=int(match.group(2)),
                url=str(category.get("link") or ""),
                sourceId=spec.get("id", "wp-categories"),
                tier=int(spec.get("tier", 3)),
                evidence=f"{name}（{category.get('count')} 篇）",
            )
        )
    return refs


def _enumWordpressLatestPosts(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """WordPress 最新文章接口：站方最近更新，用于期次标签不规范的站。"""
    data = fetchJson(
        spec["url"],
        httpCfg.get("userAgent", ""),
        timeout=httpCfg.get("timeout", 30),
        maxRetries=httpCfg.get("maxRetries", 3),
        retryInterval=httpCfg.get("retryInterval", 30),
    )
    if not isinstance(data, list) or not data:
        return []
    post = data[0]
    title = re.sub(r"<[^>]+>", "", str((post.get("title") or {}).get("rendered") or ""))
    match = _LABEL_ISSUE_RE.search(title)
    year = int(match.group(1)) if match else int(str(post.get("date", today.year))[:4] or today.year)
    issue = int(match.group(2)) if match else 0
    return [
        IssueRef(
            year=year,
            issue=issue,
            url=str(post.get("link") or ""),
            sourceId=spec.get("id", "wp-latest"),
            tier=int(spec.get("tier", 2)),
            evidence=f"{title} / {post.get('date')}",
        )
    ]


def _wechatUrl(spec: dict, state, journalName: str) -> str:
    """推文地址优先取配置，其次取 `discover --record-url` 记下来的那条。"""
    pinned = (spec.get("url") or "").strip()
    if pinned:
        return pinned
    if state is None:
        return ""
    recorded = state.getManualIssueUrl(journalName, spec.get("id", ""))
    return (recorded or "").strip()


def _enumWechatToc(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """微信公众号目录推文：《数字人文》这类集刊的最新一期只在这里公告。

    公众号在微信外没有可列举的文章列表，往期推文也不互链，所以本源只能在「有人贴出
    链接」之后确认它宣告的是哪一期；发现新推文本身不可自动化，这是站方限制不是实现缺陷。
    """
    url = _wechatUrl(spec, state, journalCfg.get("name", ""))
    if not url:
        name = journalCfg.get("name", "")
        sourceId = spec.get("id", "wechat_toc")
        raise ManualSourceNeeded(
            f"暂无推文链接；拿到最新目录推文后运行 "
            f"dhgleaner discover --journal {name} --record-url <推文地址> --source {sourceId}"
        )
    html = _fetchHtml(spec, url, httpCfg)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    title = ""
    ogTitle = soup.find("meta", property="og:title")
    if ogTitle and ogTitle.get("content"):
        title = ogTitle["content"]
    if not title:
        node = soup.find("h1") or soup.find("h2")
        title = node.get_text(" ", strip=True) if node else text[:80]
    # 校验用「标题 + 正文」：推文标题只在 meta 里，get_text 拿不到它。
    required = spec.get("requiredPageText") or []
    page = f"{title} {text}"
    missing = [token for token in required if token not in page]
    if missing:
        raise ValueError(f"页面缺少必要文本 {missing}，疑似非目标推文")
    match = _LABEL_ISSUE_RE.search(title) or _LABEL_ISSUE_RE.search(text[:400])
    if not match:
        return []
    return [
        IssueRef(
            year=int(match.group(1)),
            issue=int(match.group(2)),
            url=url,
            sourceId=spec.get("id", "wechat-toc"),
            tier=int(spec.get("tier", 1)),
            evidence=f"{title[:60]}",
        )
    ]


def _enumManualNote(spec: dict, journalCfg: dict, httpCfg: dict, state, today) -> List[IssueRef]:
    """没有任何可列举来源的刊：如实承认「这一层得等人」，不做假探测。

    实测《数位典藏与数位人文》的「各期目次」页静态 HTML 里只有活动/会议条目，
    期次清单不在可直接访问的公开页面上 —— 与其编一个抓不到的枚举器，不如标成人工。
    """
    name = journalCfg.get("name", "")
    sourceId = spec.get("id", "manual")
    recorded = state.getManualIssueUrl(name, sourceId) if state else ""
    hint = f"已记录目录页 {recorded}" if recorded else (
        f"dhgleaner discover --journal {name} --record-url <目录页> --source {sourceId}"
    )
    raise ManualSourceNeeded(f"该刊无公开可列举的期次索引，需人工确认；{hint}")


class ManualSourceNeeded(Exception):
    """该源需要人工提供链接才能继续 —— 不是失败，是「等人」。"""


ENUMERATORS: dict[str, Callable] = {
    "archive_volumn_links": _enumArchiveVolumn,
    "archive_yvi_links": _enumArchiveYvi,
    "cnki_cbpt_current": _enumCnkiCurrent,
    "founder_period_tree": _enumFounderTree,
    "journalx_quarter_scan": _enumJournalxQuarters,
    "wordpress_issue_categories": _enumWordpressCategories,
    "wordpress_latest_posts": _enumWordpressLatestPosts,
    "wechat_toc_issue": _enumWechatToc,
    "manual_note": _enumManualNote,
}

#: 每种源对应的「拿到这一期正文」的动作；写在配置里，免得把站点怪癖固化进代码。
FETCH_ACTIONS = {
    "capture": "capture --journal {journal} --year {year} --issue {issue}",
    "capture-current": "capture --journal {journal}",
    "capture-url": "capture --journal {journal} --url {url}",
    "channel": "capture-channel --journal {journal} --channel {channel}",
    "harvest": "harvest --journal {journal} --year {year}",
    "manual": "capture --journal {journal} --url <目录页>（这一期只有人工源公告，官方逐篇页可能尚未上线）",
}
