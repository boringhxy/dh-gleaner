"""日志初始化。

关键约束：日志**只走 stderr**。

原因是 MCP 协议用 stdout 传 JSON-RPC，任何一行 `print` / StreamHandler(sys.stdout)
都会污染协议流，导致客户端解析失败。把日志统一钉在 stderr 之后，
CLI 的 stdout 也顺带变干净了（只剩真正的结果输出，方便管道处理）。
"""

from __future__ import annotations

import logging
import sys
from typing import IO

from .paths import getPaths, resolveRuntimePath

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setupLogging(logFile: str, stream: IO[str] | None = None, level: int = logging.INFO) -> logging.Logger:
    """配置根日志：文件 + 控制台（默认 stderr）。

    日志文件不可写时降级为「仅控制台」，不阻断主流程。
    """
    console = stream if stream is not None else sys.stderr
    handlers: list[logging.Handler] = [logging.StreamHandler(console)]

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
