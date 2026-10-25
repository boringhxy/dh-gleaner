"""日志初始化。

关键约束：日志**只走 stderr**。

原因是 MCP 协议用 stdout 传 JSON-RPC，任何一行 `print` / StreamHandler(sys.stdout)
都会污染协议流，导致客户端解析失败。把日志统一钉在 stderr 之后，
CLI 的 stdout 也顺带变干净了（只剩真正的结果输出，方便管道处理）。
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import IO

from .paths import getPaths, resolveRuntimePath

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def forceUtf8(*streams) -> None:
    """把终端流固定成 UTF-8，已经是 UTF-8 的不动。

    Windows 在非 UTF-8 区域里默认给控制台 cp1252：本工具的日志与结果全是中文，
    `logging` 会把 `UnicodeEncodeError` 吞成一行「--- Logging error ---」，终端上
    什么有效信息都看不到（`print` 那条路更直接，当场抛错）。MCP 的 JSON-RPC 本来就
    要求 UTF-8，所以这个固定对 stdio 传输只有好处。

    流可能不是真的终端（测试里的 StringIO、被重定向的管道），`reconfigure` 未必可用，
    失败就当没这回事。
    """
    for stream in streams:
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
            continue
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")


def setupLogging(logFile: str, stream: IO[str] | None = None, level: int = logging.INFO, *, writeFile: bool = True) -> logging.Logger:
    """配置根日志：文件 + 控制台（默认 stderr）。

    日志文件不可写时降级为「仅控制台」，不阻断主流程。
    """
    console = stream if stream is not None else sys.stderr
    forceUtf8(console)
    handlers: list[logging.Handler] = [logging.StreamHandler(console)]

    if writeFile:
        logPath = resolveRuntimePath(logFile, getPaths().defaultLogFile)
        try:
            logPath.parent.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(logPath, encoding="utf-8"))
        except OSError as e:
            print(f"日志文件不可写，仅输出到终端: {logPath} ({e})", file=sys.stderr)

    root = logging.getLogger()
    root.handlers.clear()
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers, force=True)

    # 这两家第三方库在 INFO 级别会刷屏，压到 WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return root
