"""MCP server 层：把 dhgleaner 的能力包装成标准工具接口。

外部客户端（Claude Desktop / Cursor / WorkBuddy…）通过 stdio 连上 `dhgleaner-mcp`，
即可用自然语言驱动本工具抓目录、读清单、预览与导入。

设计要点见 `server.py` 的模块文档；返回契约见 `errors.py`。

注意：这里**刻意不导入 `.server`**。否则 `python -m dhgleaner.mcp.server`
会先触发包初始化、再执行同名子模块，导致 runpy 的重复导入警告。
"""

__all__: list[str] = []
