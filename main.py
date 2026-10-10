#!/usr/bin/env python3
"""兼容入口 —— 等价于 `python -m dhgleaner`。

保留这个文件，是为了让改造前就在使用的 `python main.py <子命令>` 继续可用。
新用法请直接用命令行入口 `dhgleaner <子命令>` 或 `python -m dhgleaner <子命令>`。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dhgleaner.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
