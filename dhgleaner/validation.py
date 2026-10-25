"""输入校验与期刊名归一化。

CLI 与 MCP 共用同一套校验。所有失败一律抛 `ValidationError`，
**不再使用 SystemExit** —— SystemExit 在命令行里只是退出码，
但在 MCP server 进程里会直接把整个服务杀掉。
"""

from __future__ import annotations

from .models import IssueInfo

JOURNAL_ALIASES = {
    "数字人文研究": "数字人文研究",
    "dhr": "数字人文研究",
    "DHR": "数字人文研究",
    "数字人文": "数字人文",
    "szrw": "数字人文",
    "SZRW": "数字人文",
    "中国数字人文": "中国数字人文",
    "zgszrw": "中国数字人文",
    "数位典藏与数位人文": "数位典藏与数位人文",
    "數位典藏與數位人文": "数位典藏与数位人文",
    "tadh": "数位典藏与数位人文",
    "图书馆杂志": "图书馆杂志",
    "tsgzz": "图书馆杂志",
    "图书馆论坛": "图书馆论坛",
    "tsglt": "图书馆论坛",
    # 散篇 harvest 期刊（图情/信息刊，无常设数字人文栏目）
    "现代情报": "现代情报",
    "xdqb": "现代情报",
    "XDQB": "现代情报",
    "情报科学": "情报科学",
    "qbkx": "情报科学",
    "QBKX": "情报科学",
    "中国图书馆学报": "中国图书馆学报",
    "jtlsc": "中国图书馆学报",
    "zgtsgxb": "中国图书馆学报",
    "国家图书馆学刊": "国家图书馆学刊",
    "gtxk": "国家图书馆学刊",
    "gjtxgkx": "国家图书馆学刊",
    "数字图书馆论坛": "数字图书馆论坛",
    "dlf": "数字图书馆论坛",
    "sztsglt": "数字图书馆论坛",
    "图书情报知识": "图书情报知识",
    "tsqbzs": "图书情报知识",
    "信息资源管理学报": "信息资源管理学报",
    "xxzyglxb": "信息资源管理学报",
}

#: 「本次不要导入」的口令，与 selection 模块共用
SKIP_TOKENS = {"都不要", "无", "none", "", "None", "null"}


class ValidationError(Exception):
    """用户输入不合法。调用方负责转成可读提示，而不是终止进程。"""


def normalizeJournalName(value: str | None) -> str:
    name = (value or "").strip()
    return JOURNAL_ALIASES.get(name, name)


def knownJournalNames(cfg: dict) -> set[str]:
    return {journal["name"] for journal in cfg.get("journals", [])}


def availableJournalsText(cfg: dict) -> str:
    return ", ".join(sorted(knownJournalNames(cfg)))


def journalConfigByName(cfg: dict, name: str) -> dict:
    for journal in cfg.get("journals", []):
        if journal.get("name") == name:
            return journal
    return {}


def isHarvestOnly(cfg: dict, name: str) -> bool:
    """该期刊是否只能走 harvest（散篇期刊，无常设数字人文栏目、无稳定当期页）。"""
    return bool(journalConfigByName(cfg, name).get("harvestOnly"))


def buildTarget(year: int | None = None, issue: int | None = None, volume: int | None = None) -> dict | None:
    """把 --year/--issue/--volume 规约成 captureAll 需要的 target。"""
    if year is None and issue is None and volume is None:
        return None
    if year is None or issue is None:
        raise ValidationError("指定目标期次时必须同时提供 year 和 issue")
    target: dict = {"year": year, "issue": issue}
    if volume is not None:
        target["volume"] = volume
    return target


def resolveCaptureJournalName(journal: str | None, allJournals: bool, cfg: dict) -> str:
    """校验 --journal / --all-journals 的组合，返回归一化后的期刊名（全抓时为空串）。"""
    journalName = normalizeJournalName(journal)
    if journalName and allJournals:
        raise ValidationError("journal 和 allJournals 只能二选一")
    if not journalName and not allJournals:
        raise ValidationError("请用 --journal 指定期刊；如需抓取全部期刊，请显式使用 --all-journals")
    known = knownJournalNames(cfg)
    if journalName and journalName not in known:
        raise ValidationError(f"未知期刊: {journalName}。可用期刊: {availableJournalsText(cfg)}")
    return journalName


def resolveCaptureRequest(
    cfg: dict,
    journal: str | None = None,
    allJournals: bool = False,
    year: int | None = None,
    issue: int | None = None,
    volume: int | None = None,
    url: str = "",
) -> tuple[dict | None, str]:
    """校验一次 capture 请求，返回 (target, journalName)。"""
    target = buildTarget(year, issue, volume)
    journalName = resolveCaptureJournalName(journal, allJournals, cfg)
    if journalName and not url and isHarvestOnly(cfg, journalName):
        raise ValidationError(
            f"《{journalName}》是散篇期刊（无常设数字人文栏目），请改用 harvest 按年采集，"
            f"如：dhgleaner harvest --journal {journalName} --year 2026"
        )
    if url and not journalName:
        raise ValidationError("使用 --url 时必须同时指定 --journal")
    if not target and not url:
        raise ValidationError("请指定目标期次：year+issue；或使用 journal+url 指定目录页")
    return target, journalName


def resolveChannelRequest(
    cfg: dict,
    journal: str | None = None,
    channel: str | None = None,
) -> tuple[dict, str, str]:
    """校验一次 capture-channel 请求，返回 (journalConfig, journalName, channelName)。"""
    journalName = normalizeJournalName(journal)
    if not journalName:
        raise ValidationError("请用 --journal 指定期刊")
    known = {j["name"]: j for j in cfg.get("journals", [])}
    if journalName not in known:
        raise ValidationError(f"未知期刊: {journalName}。可用期刊: {availableJournalsText(cfg)}")
    channelName = (channel or "").strip()
    if not channelName:
        raise ValidationError("请用 --channel 指定栏目名")
    return known[journalName], journalName, channelName


#: 支持「按年枚举全目录」harvest 的解析器
HARVEST_PARSERS = {"founder", "journalx", "magtech"}


def resolveHarvestRequest(
    cfg: dict,
    journal: str | None = None,
    year: int | None = None,
) -> tuple[str, int]:
    """校验一次 harvest 请求，返回 (journalName, year)。

    journalName 为空串表示 harvest 配置中所有标了 ``harvestOnly`` 的散篇期刊。
    """
    journalName = normalizeJournalName(journal)
    known = {j["name"]: j for j in cfg.get("journals", [])}
    if journalName:
        if journalName not in known:
            raise ValidationError(f"未知期刊: {journalName}。可用期刊: {availableJournalsText(cfg)}")
        parser = known[journalName].get("parser")
        if parser not in HARVEST_PARSERS:
            raise ValidationError(
                f"《{journalName}》不支持按年 harvest（解析器 {parser}）；请改用 capture 抓取当期。"
            )
    if not year:
        raise ValidationError("请用 year 指定要 harvest 的年份，如 2026")
    try:
        yearInt = int(year)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"year 不是合法年份: {year}") from e
    return journalName, yearInt


def resolveDiscoverRequest(cfg: dict, journal: str | None = None) -> str:
    """校验 discover 请求；journal 留空表示探测配置中的全部期刊。"""
    journalName = normalizeJournalName(journal)
    if journalName and journalName not in knownJournalNames(cfg):
        raise ValidationError(f"未知期刊: {journalName}。可用期刊: {availableJournalsText(cfg)}")
    return journalName


def resolveManualSourceRequest(cfg: dict, journal: str | None, url: str, source: str = "") -> tuple[str, str]:
    """校验「记录人工发现的最新一期链接」，返回 (期刊名, 发现源 id)。

    只允许记到 `fetch=manual` 或 tier==1 的人工源上：把链接记到官方源上会让
    「官网说它是最新」和「有人贴了个链接」两件事混成一件，之后的时效判断就不可信了。
    """
    journalName = normalizeJournalName(journal)
    if not journalName:
        raise ValidationError("记录人工来源必须指定 --journal")
    if not url:
        raise ValidationError("记录人工来源必须给出 --record-url 指向的目录页/推文地址")
    known = knownJournalNames(cfg)
    if journalName not in known:
        raise ValidationError(f"未知期刊: {journalName}。可用期刊: {availableJournalsText(cfg)}")
    journalCfg = journalConfigByName(cfg, journalName)
    sources = (journalCfg.get("discovery") or {}).get("sources") or []
    manual = [s for s in sources if s.get("fetch") == "manual" or int(s.get("tier", 2)) == 1]
    if not manual:
        raise ValidationError(
            f"《{journalName}》没有人工型发现源（discovery.sources 里 tier=1 或 fetch=manual）；"
            "该刊的最新一期应由 discover 自动判定。"
        )
    if source:
        wanted = [s for s in manual if s.get("id") == source]
        if not wanted:
            raise ValidationError(
                f"《{journalName}》的人工型发现源里没有 {source}；可选："
                f"{', '.join(str(s.get('id')) for s in manual)}"
            )
        return journalName, source
    if len(manual) > 1:
        raise ValidationError(
            f"《{journalName}》有 {len(manual)} 个人工型发现源，请用 --source 指定其一："
            f"{', '.join(str(s.get('id')) for s in manual)}"
        )
    return journalName, str(manual[0].get("id"))


def isSkipToken(selection: str | None) -> bool:
    return (selection or "").strip() in SKIP_TOKENS


def describeIssue(issue: IssueInfo | None) -> str:
    return issue.label() if issue else ""
