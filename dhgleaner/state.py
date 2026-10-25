"""状态管理 — state.json 读写，幂等性保证。

两条不能破的约束：

1. **写入原子**：先写临时文件、fsync，再 `os.replace` 覆盖。进程在中途被杀也只会
   留下完整的旧文件或完整的新文件，不会出现半截 JSON。
2. **损坏不静默丢弃**：解析失败时把坏文件另存为 `.corrupt-<时间戳>` 并 `log.error`。
   静默重置会让「已处理」记录凭空消失，下次运行把老文章当新文章重复导入 Zotero。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Optional

from .models import Article, IssueInfo

log = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=8))


def _nowIso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def issueFullySeen(issueArticles: Iterable[Article]) -> bool:
    """这批同刊同期文章是否代表「整期目录已经过完一遍」。

    只有整期抓取（``sourceType == "issue"``）拿到的是完整目录。栏目抓取、按年
    harvest、人工整理清单里一期往往只有几篇，把它们全跳过/导入完就盖上「这期已
    处理」的章，之后 ``capture --dedupe`` 会在 :meth:`StateManager.isIssueProcessed`
    上直接返回空清单——那一期剩下的文章永远抓不到，而空清单来自去重属于「合法的
    空」，质量闸门不会报警，只会沉默。
    """
    return bool(issueArticles) and all(article.sourceType == "issue" for article in issueArticles)


class StateManager:
    def __init__(self, stateFile: str):
        self.stateFile = stateFile
        self.state: dict = {"journals": {}}
        self._deferDepth = 0
        self._pendingWrite = False
        self._load()

    def _load(self):
        if not os.path.exists(self.stateFile):
            return
        try:
            with open(self.stateFile, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            self._quarantineCorrupt(e)
            self.state = {"journals": {}}
            return
        if not isinstance(data, dict):
            self._quarantineCorrupt(ValueError("顶层结构不是 JSON 对象"))
            self.state = {"journals": {}}
            return
        if not isinstance(data.get("journals"), dict):
            data["journals"] = {}
        self.state = data

    def _quarantineCorrupt(self, error: Exception):
        """把损坏的 state.json 另存为 `.corrupt-<时间戳>`，绝不静默丢弃历史。"""
        backup = f"{self.stateFile}.corrupt-{datetime.now(_TZ).strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(self.stateFile, backup)
            log.error(
                "state.json 解析失败，已备份到 %s 后重新初始化；"
                "历史「已处理」记录暂缺，如需保留请从备份手工修复。原因: %s",
                backup, error,
            )
        except OSError as moveErr:
            log.error(
                "state.json 解析失败且无法备份（%s），将重新初始化。原因: %s",
                moveErr, error,
            )

    def _writeAtomic(self):
        directory = os.path.dirname(self.stateFile) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmpPath = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmpPath, self.stateFile)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmpPath)
            raise

    def _save(self):
        if self._deferDepth:
            self._pendingWrite = True
            return
        self._writeAtomic()

    @contextlib.contextmanager
    def batch(self) -> Iterator["StateManager"]:
        """把多次写入合并成一次，供批量标记路径使用，避免逐篇落盘的 O(n²) 开销。

        只用于「重跑即幂等」的批量操作（如整期标记 skipped）。写入 Zotero 的导入循环
        **不要**用它——那里每篇落盘一次是为了进程崩溃后不丢进度、重跑能跳过已写条目。
        """
        self._deferDepth += 1
        try:
            yield self
        finally:
            self._deferDepth -= 1
            if self._deferDepth == 0 and self._pendingWrite:
                self._pendingWrite = False
                self._writeAtomic()

    def _journalState(self, name: str) -> dict:
        js = self.state["journals"].get(name)
        # 逐字段补默认值，而不是只在期刊条目整个缺失时补一整套：_quarantineCorrupt
        # 明确告诉用户可以「从备份手工修复」state.json，而手工修出来的条目很容易只
        # 留下 lastIssue 这类看得见的字段。读路径用的是 `js.get(...)` tolerates 缺失，
        # 写路径 `js["processedArticles"]` 却会 KeyError——崩溃点偏偏落在导入循环里，
        # 那时前几篇已经写进 Zotero，进度和实际入库内容就对不上了。
        if not isinstance(js, dict):
            js = {}
            self.state["journals"][name] = js
        js.setdefault("lastIssue", None)
        js.setdefault("lastCheckAt", None)
        js.setdefault("latestKnown", None)
        if not isinstance(js.get("manualIssueUrls"), dict):
            js["manualIssueUrls"] = {}
        if not isinstance(js.get("processedArticles"), list):
            js["processedArticles"] = []
        if not isinstance(js.get("processedArticleMeta"), dict):
            js["processedArticleMeta"] = {}
        return js

    def updateLastCheck(self, name: str):
        js = self._journalState(name)
        js["lastCheckAt"] = _nowIso()
        self._save()

    def getLastIssue(self, name: str) -> Optional[dict]:
        return self._journalState(name).get("lastIssue")

    def getLatestKnown(self, name: str) -> Optional[dict]:
        """发现层记下的「该刊最新已知期次」，与 lastIssue（已处理到哪一期）互不干扰。"""
        return self._journalState(name).get("latestKnown")

    def recordLatestKnown(self, name: str, ref: dict):
        js = self._journalState(name)
        previous = js.get("latestKnown") or {}
        changed = not previous or previous.get("label") != ref.get("label")
        js["latestKnown"] = {**ref, "recordedAt": _nowIso(), "changedAtIssue": bool(changed)}
        self._save()

    def getManualIssueUrl(self, name: str, sourceId: str) -> str:
        return str(self._journalState(name).get("manualIssueUrls", {}).get(sourceId) or "")

    def recordManualIssueUrl(self, name: str, sourceId: str, url: str):
        js = self._journalState(name)
        js.setdefault("manualIssueUrls", {})[sourceId] = url
        self._save()

    def isIssueProcessed(self, name: str, issue: IssueInfo) -> bool:
        last = self.getLastIssue(name)
        if not last:
            return False
        return (
            last.get("year") == issue.year
            and last.get("volume") == issue.volume
            and last.get("issue") == issue.issue
        )

    def markIssueProcessed(self, name: str, issue: IssueInfo):
        js = self._journalState(name)
        js["lastIssue"] = {
            "year": issue.year,
            "volume": issue.volume,
            "issue": issue.issue,
            "publishDate": issue.publishDate,
            "key": issue.key(),
        }
        self._save()

    def isArticleProcessed(self, name: str, articleKey: str) -> bool:
        js = self._journalState(name)
        return articleKey in js.get("processedArticles", [])

    def markArticleProcessed(
        self,
        name: str,
        articleKey: str,
        zoteroKey: str = "",
        title: str = "",
        status: str = "imported",
    ):
        js = self._journalState(name)
        if articleKey not in js["processedArticles"]:
            js["processedArticles"].append(articleKey)
        js.setdefault("processedArticleMeta", {})[articleKey] = {
            "zoteroKey": zoteroKey,
            "title": title,
            "status": status,
            "date": _nowIso(),
        }
        self._save()

    def markArticlesProcessed(
        self,
        name: str,
        articles: Iterable[tuple[str, str]],
        status: str = "skipped",
    ):
        with self.batch():
            for articleKey, title in articles:
                self.markArticleProcessed(name, articleKey, title=title, status=status)
