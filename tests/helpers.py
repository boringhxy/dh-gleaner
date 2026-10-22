"""测试辅助 —— 临时数据目录与假 Zotero 客户端。"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Iterator

from dhgleaner import paths as paths_module


@contextlib.contextmanager
def tempDataDir() -> Iterator[Path]:
    """把数据目录临时指向一个空目录，退出时还原。

    所有产物路径都以该目录为根（`data/`、`logs/`、`tmp/`、`config.local.json`），
    因此用例之间互不污染，也不会写进真实项目目录。
    """
    with tempfile.TemporaryDirectory() as tmp:
        with paths_module.useDataDir(tmp) as current:
            yield current.dataDir


def writePending(payload: dict) -> Path:
    """把待筛 payload 写到当前数据目录的 data/pending.json，返回该路径。"""
    target = paths_module.getPaths().pending
    target.parent.mkdir(parents=True, exist_ok=True)
    import json

    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def pendingPayload(articles: list[dict], **overrides) -> dict:
    """构造一个合法的 pending.json 结构。"""
    payload = {
        "capturedAt": "2026-07-20T10:00:00+08:00",
        "captureType": "issue",
        "note": "",
        "markdown": "# 清单",
        "articles": articles,
    }
    payload.update(overrides)
    return payload
