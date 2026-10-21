"""解析器与 harvest 共用的文本清洗 / 前置条目识别工具。

独立成模块是为了避免循环依赖：parsers 与 harvest 都要用，而它不依赖包内任何模块。
"""

from __future__ import annotations

import re


def cleanText(s: str) -> str:
    """去掉 magtech 的 ``#br#``/``#b#`` 换行占位、私有区字符与多余空白。"""
    if not s:
        return ""
    s = re.sub(r"#/?b(?:r)?#", " ", s)
    s = re.sub(r"[\ue000-\uf8ff]", " ", s)
    s = re.sub(r"[\n\t\r]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


#: 封面 / 目次 / 征稿启事 / 卷首语 / 编委会 等非论文条目标题
FRONT_MATTER_RE = re.compile(
    r"^(封面|封底|扉页|目次|目录|英文目次|中文目次|插页|版权页?|征稿启事|征稿|启事|声明|更正|勘误|"
    r"本期导读|导读|卷首语|卷首|前言|序言|编委会|编辑部|作者简介|索引|摘要|Abstract)\s*\d*$",
    re.I,
)


def isFrontMatterTitle(title: str) -> bool:
    """标题是否属于前置/后置非论文条目（不计入全目录，也不抓详情）。"""
    return bool(FRONT_MATTER_RE.match((title or "").strip()))
