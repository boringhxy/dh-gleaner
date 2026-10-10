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


def isSkipToken(selection: str | None) -> bool:
    return (selection or "").strip() in SKIP_TOKENS


def describeIssue(issue: IssueInfo | None) -> str:
    return issue.label() if issue else ""
