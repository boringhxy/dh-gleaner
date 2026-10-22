"""解析器与 harvest 共用的文本清洗 / 前置条目与导航标题识别工具。

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


#: 站点导航 / 广告 / 平台外壳的标题词。命中说明抓到的不是文章清单。
#:
#: 分两组是因为匹配方式必须不同：中文词可以直接当子串用（中文没有词边界，
#: 「过刊浏览」出现在标题里基本就是导航）；拉丁词只能整条相等，否则一篇
#: 题为《Journal of Digital Humanities 的引文分析》的论文会被误判成导航。
NAVIGATION_SUBSTRINGS = frozenset(
    {
        "首页", "更多", "数据库", "投稿指南", "联系我们", "期刊介绍",
        "过刊浏览", "在线投稿", "下载中心", "精选期刊", "最新消息",
        "关于我们", "广告合作",
    }
)
NAVIGATION_EXACT = frozenset({"Home", "More", "Read More", "English", "About", "Journal"})
_NAVIGATION_EXACT_LOWER = frozenset(word.lower() for word in NAVIGATION_EXACT)


def _normalizeTitle(title: str) -> str:
    return re.sub(r"\s+", " ", title or "").strip()


def isNavigationTitle(title: str) -> bool:
    """标题是否是站点导航/广告外壳（capture 的质量闸门与 generic_html 共用）。"""
    normalized = _normalizeTitle(title)
    if not normalized:
        return False
    if normalized.lower() in _NAVIGATION_EXACT_LOWER:
        return True
    return any(word in normalized for word in NAVIGATION_SUBSTRINGS)


def isBlacklistedTitle(title: str, blacklist) -> bool:
    """期刊配置里自定义的标题黑名单，子串命中即算。"""
    normalized = _normalizeTitle(title)
    if not normalized or not blacklist:
        return False
    return any(word and word in normalized for word in blacklist)


#: 解码失败时替换字符 U+FFFD（&#65533;）。站点声明错编码、或 requests 的
#: apparent_encoding 猜错时就会成片出现，是「这批文本根本不可读」的硬信号。
REPLACEMENT_CHAR = "\ufffd"


def hasDecodingGarbage(*texts: str) -> bool:
    """任一文本含 U+FFFD 即认为解码出错 —— 这类清单不该当成可信结果。"""
    return any(REPLACEMENT_CHAR in (text or "") for text in texts)


_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")


def normalizeDate(raw: str) -> str:
    """把页面文本里的刊出日期规范成 ISO（``2026-06-28`` / ``2026-06`` / ``2026``）。

    解析期次的正则用的是宽松的 ``[\\d-]+``，``--``、``2026-13-40`` 这类脏值都会被抓到。
    认不出来时返回空串而不是原样保留：``zotero_client`` 会把条目的 ``date`` 回退成纯年份，
    而一个 Zotero 解析不出的怪字符串会一路带到用户的库里，比只给年份更难发现。
    """
    text = (raw or "").strip().replace(".", "-").replace("/", "-")
    match = _DATE_RE.match(text)
    if not match:
        return ""
    year, month, day = match.groups()
    if month is not None and not 1 <= int(month) <= 12:
        return ""
    if day is not None and not 1 <= int(day) <= 31:
        return ""
    if month is None:
        return year
    if day is None:
        return f"{year}-{int(month):02d}"
    return f"{year}-{int(month):02d}-{int(day):02d}"
