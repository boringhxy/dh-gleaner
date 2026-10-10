"""MCP server 入口。

启动方式（stdio 传输，供 Claude Desktop / Cursor / WorkBuddy 等客户端拉起）::

    dhgleaner-mcp
    # 或
    python -m dhgleaner.mcp.server

三条硬约束：

1. **stdout 只走 JSON-RPC**。日志在启动时被强制切到 stderr（见 `logging_setup`），
   本包内任何模块都不允许出现 `print`（pyproject 里对 `dhgleaner/mcp/` 关了 T201）。
2. **工具层不碰 CLI**。工具直接调用 `service` / `selection` 层，绝不调用 `cli.cmdXxx`。
3. **只有 `import_to_zotero` 会写 Zotero**，且需要 `confirm=true` 与 `dryRun=false` 同时成立。
"""

from __future__ import annotations

import sys

from .. import __version__
from ..config import loadConfig
from ..logging_setup import setupLogging

INSTRUCTIONS = """数字人文期刊采集器：按刊按期巡检中文期刊目录页，人工筛选后再写入 Zotero。

工作流：
1. list_journals 看支持哪些刊；run_doctor 确认环境就绪。
2. capture_issue / capture_channel 抓目录（默认 dryRun=true，只抓不落盘）。
3. list_pending_articles / get_article_abstract / search_pending_articles 读清单。
4. preview_import 预览将要导入的文章；用户确认后，用 export_review_spreadsheet 出勾选表。
5. import_to_zotero 写入 Zotero —— 必须 confirm=true 且 dryRun=false，否则只返回计划。

红线：先筛选、后导入。捕获阶段不写 Zotero、不下载 PDF。
不绕过任何验证码或登录限制；遇到 412/403 直接返回 blocked，请改用 url 指定公开目录页或手工补录。
"""


def buildServer():
    """构造 MCP server 并注册全部工具。"""
    from mcp.server.mcpserver import MCPServer

    from . import tools_capture, tools_import, tools_read

    server = MCPServer(
        name="dh-gleaner",
        title="数字人文期刊采集器",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    tools_read.register(server)
    tools_capture.register(server)
    tools_import.register(server)
    return server


def main() -> None:
    """控制台入口：把日志钉在 stderr，然后跑 stdio 服务。"""
    try:
        cfg = loadConfig()
        logFile = cfg.get("logFile", "logs/capture.log")
    except Exception:
        logFile = "logs/capture.log"
    setupLogging(logFile, stream=sys.stderr)

    try:
        server = buildServer()
    except ImportError:
        # 用 stderr 直写而不是 print：本包被 ruff 的 T201 规则保护，杜绝 stdout 污染
        sys.stderr.write('缺少 MCP 依赖。请安装：pip install "dh-gleaner[mcp]"\n')
        raise SystemExit(1) from None

    server.run("stdio")


if __name__ == "__main__":
    main()
