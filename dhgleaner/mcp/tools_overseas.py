"""Overseas source tools; no Zotero writes or authentication."""
from __future__ import annotations

from ..config import loadConfig
from ..overseas import runSourceCapture, sourceById, sourceCatalog
from ..validation import ValidationError
from .errors import failure, success
from .payloads import articleRows


def listOverseasSources(source: str = '') -> dict:
    try:
        return success(catalog=sourceById(source) if source else sourceCatalog())
    except ValidationError as error:
        return failure(str(error), kind='invalid_input')


def captureOverseasSource(source: str, year: int, url: str = '', dryRun: bool = True, limit: int = 200) -> dict:
    try:
        _, articles = runSourceCapture(source, year, loadConfig(), url, dryRun)
        return success(dryRun=dryRun, wrotePending=not dryRun, articleCount=len(articles),
                       articles=articleRows(articles, max(0, limit)),
                       access=sourceById(source), note='仅捕获题录和摘要，不下载PDF、不写Zotero。')
    except (ValidationError, OSError) as error:
        return failure(str(error), error=error)


def register(server):
    server.add_tool(listOverseasSources, name='list_overseas_sources',
                    description='查看海外数字人文来源及机构账号、网络和自动采集状态（只读）')
    server.add_tool(captureOverseasSource, name='capture_overseas_source',
                    description='捕获海外数字人文题录摘要（默认dryRun；不写Zotero、不下载PDF）')
