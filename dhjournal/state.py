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

from .models import IssueInfo

log = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=8))


def _nowIso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


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
        if name not in self.state["journals"]:
            self.state["journals"][name] = {
                "lastIssue": None,
                "lastCheckAt": None,
                "processedArticles": [],
                "processedArticleMeta": {},
            }
        return self.state["journals"][name]

    def updateLastCheck(self, name: str):
        js = self._journalState(name)
        js["lastCheckAt"] = _nowIso()
        self._save()

    def getLastIssue(self, name: str) -> Optional[dict]:
        return self._journalState(name).get("lastIssue")

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
