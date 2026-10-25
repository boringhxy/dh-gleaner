"""业务服务层：只返回数据，不打印。

CLI 的 `cmdXxx` 与 MCP 的工具函数都调用这一层，所以这里必须满足两条纪律：

1. **不 print**：所有输出由调用方决定（CLI 打印给人看，MCP 序列化成 JSON）。
   这也是 MCP 模式下 stdout 不被污染的前提。
2. **不抛 SystemExit**：输入校验交给 `validation`，失败抛 `ValidationError`。

数据产物（pending.json / review.md / state.json / 备份）的路径一律经 `paths.getPaths()`，
因此「项目根 legacy 模式」与「装到 ~/.dhgleaner」两种情形行为一致。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from .capture import CaptureFailure, assessBatchQuality, captureAll, captureChannel
from .config import credentialHint, isZoteroConfigured, loadConfig
from .discovery import discoverAll
from .harvest import harvestAll
from .importer import importArticlesDetailed
from .models import Article, IssueInfo
from .paths import configTemplatePath, getPaths, resolveRuntimePath
from .presenter import renderCatalog
from .state import StateManager
from .zotero_client import ZoteroClient

log = logging.getLogger(__name__)
_TZ = timezone(timedelta(hours=8))

DEPENDENCY_MODULES = [
    ("requests", "requests"),
    ("beautifulsoup4", "bs4"),
    ("lxml", "lxml"),
    ("pyzotero", "pyzotero"),
]


# --------------------------------------------------------------------------
# 路径与配置
# --------------------------------------------------------------------------

def statePath(cfg: dict) -> Path:
    return resolveRuntimePath(cfg.get("stateFile"), getPaths().defaultStateFile)


def tempDir(cfg: dict) -> Path:
    return resolveRuntimePath(cfg.get("tempDir"), getPaths().defaultTempDir)


def logPath(cfg: dict) -> Path:
    return resolveRuntimePath(cfg.get("logFile"), getPaths().defaultLogFile)


def stateManager(cfg: dict, *, readOnly: bool = False) -> StateManager:
    return StateManager(str(statePath(cfg)), readOnly=readOnly)


def saveCredentials(libraryId: str, apiKey: str) -> tuple[bool, str]:
    """把使用者自己的 Zotero 凭据写入 `<数据目录>/config.local.json`（仅此文件）。

    安全约束：只写 config.local.json（.gitignore 已忽略），绝不碰 config.json、
    绝不回显、绝不上传。写入用临时文件 + `os.replace` 原子落盘，并把权限收到 0600。
    已存在时先另存 `.bak-<时间戳>`，避免覆盖掉用户原有凭据。
    返回 (是否成功, 成功时为文件路径 / 失败时为错误说明)。
    """
    path = getPaths().configLocalPath
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(
                f"{path.stem}.bak-{datetime.now(_TZ).strftime('%Y%m%d-%H%M%S-%f')}{path.suffix}"
            )
            shutil.copy2(path, backup)
            with contextlib.suppress(OSError):
                os.chmod(backup, 0o600)
        payload = {"zotero": {"webLibraryId": libraryId.strip(), "webApiKey": apiKey.strip()}}
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-local-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        return True, str(path)
    except OSError as e:
        log.error("写入 config.local.json 失败: %s", e)
        return False, str(e)


# --------------------------------------------------------------------------
# 数据产物读写
# --------------------------------------------------------------------------

def backupExistingPendingFiles() -> list[Path]:
    """覆盖筛选数据前备份旧 pending/review，避免误删待处理清单。"""
    existing = [path for path in (getPaths().pending, getPaths().review) if path.exists()]
    if not existing:
        return []
    timestamp = datetime.now(_TZ).strftime("%Y%m%d-%H%M%S-%f")
    getPaths().backupDir.mkdir(parents=True, exist_ok=True)
    backups = []
    for path in existing:
        backupPath = getPaths().backupDir / f"{path.stem}-{timestamp}{path.suffix}"
        shutil.copy2(path, backupPath)
        backups.append(backupPath)
    return backups


def savePending(
    markdown: str,
    articles: Sequence[Article],
    backup: bool = False,
    note: str = "",
    captureType: str = "issue",
    preserveMetadata: bool = False,
) -> list[Path]:
    """保存捕获/导入结果供后续阶段使用，返回本次备份文件列表。"""
    getPaths().pending.parent.mkdir(parents=True, exist_ok=True)
    backups = backupExistingPendingFiles() if backup else []
    data = {
        "capturedAt": datetime.now(_TZ).isoformat(timespec="seconds"),
        "captureType": captureType,
        "note": note,
        "markdown": markdown,
        "articles": [],
    }
    if preserveMetadata:
        previous = loadPendingData()
        for key in ("capturedAt", "captureType", "note"):
            if key in previous:
                data[key] = previous[key]
    for article in articles:
        item = article.toDict()
        item["_globalIndex"] = getattr(article, "_globalIndex", 0)
        data["articles"].append(item)
    _savePendingArtifacts(json.dumps(data, ensure_ascii=False, indent=2), markdown)
    return backups


def _stageArtifact(path: Path, content: bytes) -> str:
    """在目标文件旁暂存完整内容；提交前的任何写入失败都不碰旧文件。"""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(temporary)
        raise


def _savePendingArtifacts(payload: str, markdown: str) -> None:
    """pending 为权威数据，最后提交；提交失败时还原已更新的 review。"""
    paths = getPaths()
    staged: list[str] = []
    reviewCommitted = False
    rollback = None
    try:
        if paths.review.exists():
            rollback = _stageArtifact(paths.review, paths.review.read_bytes())
            staged.append(rollback)
        pending = _stageArtifact(paths.pending, payload.encode("utf-8"))
        staged.append(pending)
        review = _stageArtifact(paths.review, markdown.encode("utf-8"))
        staged.append(review)
        os.replace(review, paths.review)
        reviewCommitted = True
        os.replace(pending, paths.pending)
    except OSError:
        if reviewCommitted:
            if rollback:
                os.replace(rollback, paths.review)
            else:
                paths.review.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged:
            with contextlib.suppress(OSError):
                os.remove(temporary)


def saveCaptureStatus(status: str, message: str, results=None, failures=None) -> Path | None:
    """记录最近一次 capture 状态；失败时不覆盖旧 review。"""
    getPaths().captureStatus.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "capturedAt": datetime.now(_TZ).isoformat(timespec="seconds"),
        "status": status,
        "message": message,
        "reviewPath": str(getPaths().review),
        "pendingPath": str(getPaths().pending),
        "reviewIsStale": status != "success",
        "results": [],
        "failures": [f.toDict() for f in failures or []],
    }
    for name, issue, articles in results or []:
        payload["results"].append({
            "journal": name,
            "issue": issue.label() if issue else "",
            "articleCount": len(articles or []),
        })
    try:
        getPaths().captureStatus.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return getPaths().captureStatus
    except OSError as e:
        log.error("capture 状态文件不可写: %s (%s)", getPaths().captureStatus, e)
        return None


def writeTextArtifact(path: Path, content: str) -> str | None:
    """保存运行报告。返回 None 表示成功，否则返回错误说明，不影响主流程。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return None
    except OSError as e:
        log.error("报告不可写，未保存: %s (%s)", path, e)
        return str(e)


def loadPendingData() -> dict:
    if not getPaths().pending.exists():
        return {}
    try:
        return json.loads(getPaths().pending.read_text(encoding="utf-8"))
    except Exception:
        return {}


def loadPending() -> tuple[str, List[Article]]:
    """加载上次捕获结果。Returns (markdown, articles)。"""
    data = loadPendingData()
    if not data:
        return "", []
    articles = [Article.fromDict(d) for d in data.get("articles", [])]
    # 两个列表同源同长，strict=False 保持与改造前一致的行为
    for raw, article in zip(data.get("articles", []), articles, strict=False):
        article._globalIndex = raw.get("_globalIndex", 0)
    return data.get("markdown", ""), articles


def loadCaptureStatus() -> dict:
    path = getPaths().captureStatus
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------
# 捕获
# --------------------------------------------------------------------------

@dataclass
class CaptureOutcome:
    """一次抓取的结果。`status` 取值：success / suspect / failed。"""

    journal: str
    issue: str
    markdown: str
    articles: List[Article] = field(default_factory=list)
    quality: str = ""
    reason: str = ""
    status: str = "failed"
    backups: List[Path] = field(default_factory=list)
    wrotePending: bool = False
    collected: List[tuple] = field(default_factory=list, repr=False)
    failures: List[CaptureFailure] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def articleCount(self) -> int:
        return len(self.articles)

    @property
    def blockedJournals(self) -> List[str]:
        """被站点明确拒绝自动化的刊 —— 重试无用，得换 URL 或转人工。"""
        return [f.journal for f in self.failures if f.kind == "blocked"]


def freshnessWarnings(state: StateManager, results: Sequence[tuple]) -> List[str]:
    """抓到的期次若早于发现层记录的最新已知期次，如实提醒一句。

    只提醒、不改 status 也不改退出码：抓到旧期不是「抓坏了」，清单本身是有效的；
    但如果不说出来，「官网落后 3 期」和「确实没有新刊」在输出里就一模一样。
    """
    warnings: List[str] = []
    for name, issue, _articles in results:
        # harvest 的 results 只有年份（issue=0），拿它比期次只会造成假警报。
        if not issue or not issue.year or not issue.issue:
            continue
        known = state.getLatestKnown(name) or {}
        if not known.get("year"):
            continue
        if (issue.year, issue.issue) >= (known.get("year"), known.get("issue")):
            continue
        warnings.append(
            f"《{name}》本次抓到 {issue.label()}，"
            f"但发现层已知更新的一期是 {known.get('label')}（来源 {known.get('sourceId')}）。"
            f"若官方逐篇页尚未上线该期，用 `dhgleaner discover --journal {name}` 看该走哪条路。"
        )
    return warnings



def _finishCapture(
    outcome: CaptureOutcome,
    *,
    captureType: str,
    note: str,
    dryRun: bool,
) -> CaptureOutcome:
    """按抓取质量决定是否覆盖 pending；dryRun 时一律只读。"""
    if dryRun:
        return outcome

    if outcome.articleCount > 0 and outcome.quality == "success":
        try:
            outcome.backups = savePending(
                outcome.markdown, outcome.articles, backup=True, note=note, captureType=captureType
            )
        except OSError as error:
            outcome.status = "failed"
            outcome.reason = f"清单保存失败，未提交新的待筛批次：{error}"
            saveCaptureStatus("failed", outcome.reason, outcome.collected, outcome.failures)
            return outcome
        saveCaptureStatus("success", f"共捕获 {outcome.articleCount} 篇文章", outcome.collected, outcome.failures)
        outcome.wrotePending = True
    elif outcome.articleCount > 0:
        saveCaptureStatus(
            "suspect",
            f"本次抓取疑似误抓，旧筛选清单未覆盖：{outcome.reason}",
            outcome.collected,
            outcome.failures,
        )
        outcome.status = "suspect"
    else:
        saveCaptureStatus(
            "failed",
            f"本次未捕获到文章，旧筛选清单未覆盖：{outcome.reason}" if outcome.reason else "本次未捕获到文章，旧筛选清单未覆盖",
            outcome.collected,
            outcome.failures,
        )
        outcome.status = "failed"
    return outcome


def captureIssue(
    cfg: dict,
    *,
    target: dict | None = None,
    journalName: str = "",
    url: str = "",
    dedupe: bool = False,
    dryRun: bool = False,
) -> CaptureOutcome:
    """按年期或目录页 URL 抓取。journalName 为空串表示抓配置中的全部期刊。"""
    state = stateManager(cfg, readOnly=dryRun)
    results, failures = captureAll(
        cfg["journals"],
        cfg["http"],
        state,
        force=True,
        target=target,
        journalName=journalName,
        explicitUrl=url or "",
        dedupe=True if dedupe else None,
    )
    markdown, articles = renderCatalog(results)
    firstIssue: IssueInfo | None = results[0][1] if results else None
    quality, reason = assessBatchQuality(results, failures, captureType="issue")
    outcome = CaptureOutcome(
        journal=journalName or "全部期刊",
        issue=firstIssue.label() if firstIssue else "",
        markdown=markdown,
        articles=articles,
        quality=quality,
        reason=reason,
        status=quality,
        collected=results,
        failures=failures,
        warnings=freshnessWarnings(state, results),
    )
    return _finishCapture(outcome, captureType="issue", note="", dryRun=dryRun)


def captureJournalChannel(
    cfg: dict,
    *,
    journalConfig: dict,
    journalName: str,
    channelName: str,
    url: str = "",
    dedupe: bool = False,
    dryRun: bool = False,
) -> CaptureOutcome:
    """按栏目抓取跨期文章清单。"""
    state = stateManager(cfg, readOnly=dryRun)
    issue, articles, failure = captureChannel(
        journalConfig,
        cfg["http"],
        state,
        channelName=channelName,
        explicitUrl=url or "",
        dedupe=bool(dedupe),
    )
    results = [(journalName, issue, articles)]
    failures = [failure] if failure else []
    markdown, rendered = renderCatalog(results)
    quality, reason = assessBatchQuality(results, failures, captureType="channel")
    note = f"栏目抓取: 《{journalName}》{channelName}；每篇文章保留原站点年卷期。"
    outcome = CaptureOutcome(
        journal=journalName,
        issue=issue.label() if issue else "",
        markdown=markdown,
        articles=rendered,
        quality=quality,
        reason=reason,
        status=quality,
        collected=results,
        failures=failures,
        warnings=freshnessWarnings(state, results),
    )
    return _finishCapture(outcome, captureType="channel", note=note, dryRun=dryRun)


def captureHarvest(
    cfg: dict,
    *,
    year: int,
    journalName: str = "",
    withAbstracts: bool = True,
    dedupe: bool = False,
    dhOnly: bool = True,
    dryRun: bool = False,
) -> CaptureOutcome:
    """按年 harvest 散篇期刊：全年全目录 → DH 关键词筛 → 落盘待筛清单。

    与 captureIssue / captureJournalChannel 并列的第三种采集流程；结果同样经
    renderCatalog → 质量闸门 → savePending，因此 screen / import 下游照常可用。
    journalName 为空串时 harvest 配置中所有标了 ``harvestOnly`` 的散篇期刊。
    """
    results, failures = harvestAll(
        cfg["journals"],
        cfg["http"],
        stateManager(cfg, readOnly=dryRun),
        year=year,
        journalName=journalName,
        withAbstracts=withAbstracts,
        dedupe=dedupe,
        dhOnly=dhOnly,
    )
    markdown, articles = renderCatalog(results)
    quality, reason = assessBatchQuality(results, failures, captureType="harvest")
    scope = f"《{journalName}》" if journalName else "全部散篇期刊"
    note = (
        f"{year} 年散篇 harvest：{scope}；"
        + ("仅保留 DH 命中文章。" if dhOnly else "保留全目录并已打 DH 标签。")
    )
    outcome = CaptureOutcome(
        journal=journalName or "散篇期刊",
        issue=f"{year}年",
        markdown=markdown,
        articles=articles,
        quality=quality,
        reason=reason,
        status=quality,
        collected=results,
        failures=failures,
    )
    return _finishCapture(outcome, captureType="harvest", note=note, dryRun=dryRun)


# --------------------------------------------------------------------------
# 发现层：各刊「最新已知期次」探测
# --------------------------------------------------------------------------

def discoverLatest(
    cfg: dict,
    *,
    journalName: str = "",
    record: bool = True,
) -> list:
    """探测各刊当前最新的已知期次；journalName 为空串表示全部。

    `record=True` 时把结论写进 state.json 的 `latestKnown`；不管是否落盘，都要读 state，
    因为 tier-1 人工源（如微信目录推文）的链接就存在那里。
    除 state.json 外不写任何数据产物、不碰 Zotero。
    """
    return discoverAll(
        cfg,
        journalName=journalName,
        state=stateManager(cfg, readOnly=not record),
        record=record,
    )


def recordManualIssueUrl(cfg: dict, journalName: str, sourceId: str, url: str) -> dict:
    """记下人工发现的最新一期来源（如微信公众号目录推文），供 tier-1 发现源读取。"""
    state = stateManager(cfg)
    state.recordManualIssueUrl(journalName, sourceId, url)
    return {"journal": journalName, "sourceId": sourceId, "url": url}


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------

@dataclass
class ImportOutcome:
    report: str
    reportPath: Path | None = None
    selectedCount: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    aborted: bool = False
    abortReason: str = ""
    createdCollections: List[str] = field(default_factory=list)
    localSaveError: str = ""


def previewArticles(selected: Sequence[Article]) -> list[dict]:
    """导入预览：只列出将要写入 Zotero 的文章，不产生任何副作用。"""
    rows = []
    for position, article in enumerate(selected, 1):
        rows.append({
            "position": position,
            "index": getattr(article, "_globalIndex", 0),
            "title": article.title,
            "journal": article.journal,
            "issue": article.issueDisplay or article.issueInfo().label(),
            "authors": list(article.authors),
        })
    return rows


def runImport(
    selected: Sequence[Article],
    articles: Sequence[Article],
    markdown: str,
    cfg: dict,
    *,
    writeArtifacts: bool = True,
) -> ImportOutcome:
    """把选中文章写入 Zotero。**这是唯一会写 Zotero 的函数。**

    调用方必须先取得用户的显式确认；本函数自身不做任何确认判断。
    """
    zotero = ZoteroClient(cfg["zotero"])
    state = stateManager(cfg)
    journalConfigs = {j["name"]: j for j in cfg.get("journals", [])}
    summary = importArticlesDetailed(
        list(selected),
        zotero,
        state,
        userAgent=cfg["http"].get("userAgent", ""),
        tempDir=str(tempDir(cfg)),
        journalConfigs=journalConfigs,
        allPendingArticles=list(articles),
    )
    report = summary.report
    reportPath = None
    localSaveError = summary.localSaveError
    # 预检中止（没有可导入文章 / Zotero 连不上 / Collection 缺失）时一个字都不落盘：
    # 既不改 pending.json、也不重写 review.md。历史教训：早期实现无条件 savePending，
    # 于是「凭据没配好」这种纯失败场景也会刷新 capturedAt，并把已标 presented 的文章
    # 打回 selected，使已经看过（甚至已经导入）的文章重新冒回待筛清单。
    # 诊断信息不会丢——`report` 字段本身包含中止原因，会上报给调用方。
    if writeArtifacts and not summary.aborted:
        try:
            savePending(markdown, articles, preserveMetadata=True)
        except OSError as error:
            localSaveError = "; ".join(filter(None, (localSaveError, str(error))))
            report += f"\n\n⚠️ 本地清单保存失败：{error}。上面的 Zotero 写入结果仍然有效，请勿据此认为未写入。"
        reportPath = getPaths().importReport
        if writeTextArtifact(reportPath, report) is not None:
            reportPath = None
    return ImportOutcome(
        report=report,
        reportPath=reportPath,
        selectedCount=len(selected),
        imported=summary.imported,
        skipped=summary.skipped,
        failed=summary.failed,
        aborted=summary.aborted,
        abortReason=summary.abortReason,
        createdCollections=list(summary.createdCollections),
        localSaveError=localSaveError,
    )


def skipAllPending(cfg: dict) -> tuple[int, str, List[Article]]:
    """把当前待导入文章全部标记为 skipped 并落盘。"""
    from .selection import markAllPresentedAsSkipped

    markdown, articles = loadPending()
    if not articles:
        return 0, markdown, []
    count = markAllPresentedAsSkipped(articles, stateManager(cfg))
    savePending(markdown, articles, preserveMetadata=True)
    return count, markdown, articles


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------

@dataclass
class DoctorCheck:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    dataDir: str
    dataDirSource: str
    configLocalPath: str
    templatePath: str
    checks: List[DoctorCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def dependencyStatus() -> list[tuple[str, bool]]:
    return [(package, importlib.util.find_spec(module) is not None) for package, module in DEPENDENCY_MODULES]


def canWriteDir(path: Path) -> tuple[bool, str]:
    """只读检查现有目录或最近祖先的权限，不创建目录/探针文件。"""
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    ok = ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK)
    return ok, f"{path}（按现有目录权限估计；实际写入仍可能失败）"


def collectDoctorChecks(cfg: dict, *, checkZotero: bool = False, checkNetwork: bool = False) -> DoctorReport:
    """收集自检项，返回结构化结果；打印留给调用方。"""
    paths = getPaths()
    report = DoctorReport(
        dataDir=str(paths.dataDir),
        dataDirSource=paths.describeSource(),
        configLocalPath=str(paths.configLocalPath),
        templatePath=str(configTemplatePath()),
    )

    hasConfigFile = paths.configLocalPath.is_file()
    report.checks.append(DoctorCheck(
        "数据目录", paths.dataDir.exists(), f"{paths.dataDir} (来源: {paths.describeSource()})"
    ))
    report.checks.append(DoctorCheck(
        "你自己的 Zotero 配置文件",
        hasConfigFile,
        f"{paths.configLocalPath} ({'存在' if hasConfigFile else '缺失'})",
    ))
    report.checks.append(DoctorCheck(
        "配置模板（`dhgleaner init` 会替你写入凭据）", configTemplatePath().is_file(), report.templatePath
    ))
    report.checks.append(DoctorCheck("Python 版本", sys.version_info >= (3, 10), sys.version.split()[0]))

    for package, installed in dependencyStatus():
        report.checks.append(DoctorCheck(
            f"依赖 {package}",
            installed,
            "已安装" if installed else "缺失，说明安装不完整；请按 README「安装」章节用对应方式重装本包",
        ))

    for label, path in [
        ("data 目录可写", paths.pending.parent),
        ("state 目录可写", statePath(cfg).parent),
        ("tmp 目录可写", tempDir(cfg)),
        ("logs 目录可写", logPath(cfg).parent),
    ]:
        ok, detail = canWriteDir(path)
        report.checks.append(DoctorCheck(label, ok, detail))

    hasWebConfig, missingFields = isZoteroConfigured(cfg)
    report.checks.append(DoctorCheck(
        "你自己的 Zotero 凭据",
        hasWebConfig,
        "可尝试导入" if hasWebConfig else f"未配置 {missingFields}；capture/abstract 可用，import 不可用。{credentialHint()}",
    ))

    if checkZotero:
        zotero = ZoteroClient(cfg.get("zotero", {}))
        connected = zotero.testConnection()
        report.checks.append(DoctorCheck("Zotero 连接", connected, ""))
        if connected:
            for journal in cfg.get("journals", []):
                key = zotero.locateJournalCollection(journal["name"])
                report.checks.append(DoctorCheck(f"Collection 《{journal['name']}》", bool(key), key or "未找到"))

    if checkNetwork:
        report.checks.extend(_networkChecks(cfg))

    return report


def _networkChecks(cfg: dict) -> list[DoctorCheck]:
    from .capture import getParser
    from .http_util import fetchHtml

    checks: list[DoctorCheck] = []
    for journal in cfg.get("journals", []):
        if journal.get("harvestOnly"):
            continue
        label = f"抓取解析《{journal['name']}》"
        if not journal.get("currentIssueUrl"):
            checks.append(DoctorCheck(label, False, "暂无稳定公开目录页，请使用 --url 手动指定"))
            continue
        try:
            html = fetchHtml(
                journal["currentIssueUrl"],
                cfg.get("http", {}).get("userAgent", ""),
                timeout=cfg.get("http", {}).get("timeout", 30),
                maxRetries=1,
                retryInterval=0,
            )
            parser = getParser(journal["parser"], journal["name"], cfg.get("http", {}), journal)
            issue, articles = parser.parseCurrentIssue(html)
            checks.append(DoctorCheck(label, bool(articles), f"{issue.label()} / {len(articles)} 篇"))
        except Exception as e:
            checks.append(DoctorCheck(label, False, str(e)))
    return checks


# --------------------------------------------------------------------------
# Collection 目录管理（显式建目录，与导入时的「不擅自建目录」红线互不影响）
# --------------------------------------------------------------------------

@dataclass
class CollectionPlanRow:
    """单本期刊的 Collection 路径预检结果（只读）。"""

    journal: str
    path: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    resolvedKey: Optional[str] = None
    error: Optional[str] = None

    @property
    def complete(self) -> bool:
        return self.error is None and not self.missing and bool(self.resolvedKey)


@dataclass
class CollectionsReport:
    connected: bool
    rows: List[CollectionPlanRow] = field(default_factory=list)
    connectionError: str = ""

    @property
    def missingRows(self) -> List[CollectionPlanRow]:
        return [row for row in self.rows if row.missing]


def _collectionRows(zotero: ZoteroClient, cfg: dict) -> List[CollectionPlanRow]:
    rows: List[CollectionPlanRow] = []
    for journal in cfg.get("journals", []):
        plan = zotero.collectionPlan(journal["name"])
        rows.append(CollectionPlanRow(
            journal=journal["name"],
            path=list(plan.get("path", [])),
            missing=list(plan.get("missing", [])),
            resolvedKey=plan.get("resolvedKey"),
            error=plan.get("error"),
        ))
    return rows


def planCollections(cfg: dict, *, zotero: Optional[ZoteroClient] = None) -> CollectionsReport:
    """只读预检每本期刊的 Collection 路径缺哪些层级，**绝不创建**。

    供 `init-collections`（默认预览）与 `init` 向导展示「将会建哪些目录」。
    """
    zotero = zotero or ZoteroClient(cfg.get("zotero", {}))
    if not zotero.testConnection():
        return CollectionsReport(connected=False, connectionError="Zotero 连接失败或凭据未配置")
    return CollectionsReport(connected=True, rows=_collectionRows(zotero, cfg))


def ensureCollections(
    cfg: dict,
    *,
    journals: Optional[Sequence[str]] = None,
    zotero: Optional[ZoteroClient] = None,
) -> tuple[List[str], CollectionsReport]:
    """为指定期刊（默认全部）补齐缺失的 Collection 层级。**会写 Zotero。**

    调用方必须先用 `planCollections` 把「会建哪些目录」展示给用户并取得显式确认。
    返回 (本次新建的目录名列表, 建完后的复检报告)。
    """
    zotero = zotero or ZoteroClient(cfg.get("zotero", {}))
    if not zotero.testConnection():
        return [], CollectionsReport(connected=False, connectionError="Zotero 连接失败或凭据未配置")
    targets = list(journals) if journals else [j["name"] for j in cfg.get("journals", [])]
    for name in targets:
        zotero.locateJournalCollection(name, createIfMissing=True)
    created = list(getattr(zotero, "createdCollections", []) or [])
    return created, CollectionsReport(connected=True, rows=_collectionRows(zotero, cfg))


__all__ = [
    "CaptureOutcome",
    "CollectionPlanRow",
    "CollectionsReport",
    "DoctorCheck",
    "DoctorReport",
    "ImportOutcome",
    "backupExistingPendingFiles",
    "canWriteDir",
    "captureIssue",
    "captureJournalChannel",
    "collectDoctorChecks",
    "dependencyStatus",
    "discoverLatest",
    "ensureCollections",
    "freshnessWarnings",
    "loadCaptureStatus",
    "loadConfig",
    "loadPending",
    "loadPendingData",
    "logPath",
    "planCollections",
    "previewArticles",
    "recordManualIssueUrl",
    "runImport",
    "saveCaptureStatus",
    "saveCredentials",
    "savePending",
    "skipAllPending",
    "stateManager",
    "statePath",
    "tempDir",
    "writeTextArtifact",
]
