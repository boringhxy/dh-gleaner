"""数字人文 / 历史学+AI 关键词表与命中判定。

两张表来自人工整理，供 capture 与 harvest 两条流程共用，给每篇文章打「框架级标签」：

- ``KW_DIGITAL_HUMANITIES``（数字人文）= ``DH_FIELD`` 领域词，**任一命中**即算 DH 散篇。
- ``KW_HISTORY_AI``（历史学+AI）= ``HISTORY`` + ``AI_COMPUTE``，采用**共现**判定：
  ``HISTORY`` 与 ``AI_COMPUTE`` 各至少命中 1 个才算（避免「历史/文化」类泛词单独命中造成误收）。

判定口径（收紧后）：一篇文章算 DH，当且仅当「命中 DH_FIELD 领域词」**或**「历史+AI 共现」。
计算方法词 ``AI_COMPUTE``（大语言模型/生成式/知识图谱/语义/本体/可视化…）**不再单独算 DH**——
图情/信息刊里大量「AI in LIS」论文只用方法词、并无数字人文实质，单独命中会带来大量噪声；
这些方法词只在「历史+AI 共现」时作为计算侧计入。

命中一律用「子串包含」，与既有采集脚本保持一致：中文按字面匹配；英文缩写
（RAG/GIS/OCR/AIGC/GenAI/GLAM/CHGIS）按大小写敏感匹配，避免 "rag" 落进 "storage"、
"gis" 落进 "logistics" 这类英文摘要里的误命中。

刻意排除的陷阱泛词（会大量误命中，不进任何表）：
历史、古代、近代、传统、文化、演化、演变、档案、画像、记忆、文书。
偏宽、只能作为「历史+AI 共现」计算侧、命中后需结合摘要人工复核的词：本体、语义、可视化、考古。
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

from .models import Article

# --------------------------------------------------------------------------
# 词表
# --------------------------------------------------------------------------

#: 计算 / AI 方法签名词。仅作为「历史学+AI」共现判定的计算侧，**不单独算 DH**。
AI_COMPUTE: List[str] = [
    "大语言模型", "生成式", "GenAI", "AIGC", "RAG", "检索增强", "智能问答",
    "深度学习", "机器学习", "知识图谱", "本体", "语义", "知识组织", "知识发现",
    "命名实体", "实体识别", "关系抽取", "信息抽取", "文本分析", "文本挖掘",
    "语料库", "OCR", "文字识别", "图像识别", "可视化", "知识可视化", "数字孪生",
    "社会网络分析", "GIS", "地理信息系统", "虚拟数字人", "元宇宙", "虚拟现实", "增强现实",
]

#: 历史学 / 古籍 / 史料 / 历史地理（「历史学+AI」表的人文侧）
HISTORY: List[str] = [
    "古籍", "古文字", "甲骨", "金文", "简牍", "简帛", "帛书", "出土文献", "敦煌",
    "金石", "碑刻", "碑帖", "墓志", "拓片", "方志", "地方志", "家谱", "族谱",
    "契约文书", "民间文书", "舆图", "古地图", "历史地图", "年谱", "手稿", "善本",
    "刻本", "抄本", "稿本", "大藏经", "佛经", "道藏", "史料", "先秦", "秦汉",
    "魏晋", "隋唐", "唐宋", "宋元", "明清", "民国", "断代史", "史学", "史料学",
    "史源", "考证", "校勘", "训诂", "音韵", "文字学", "概念史", "观念史", "学术史",
    "社会史", "经济史", "文化史", "思想史", "数字考古", "考古", "历史人物", "人物画像",
    "历史事件", "历史地理", "历史GIS", "CHGIS", "时空演化", "时空分析", "口述历史",
    "口述史", "集体记忆", "文化记忆", "记忆研究",
]

#: 数字人文领域词（机构 / 遗产 / 典藏 / 计量等，DH 表的人文侧）
DH_FIELD: List[str] = [
    "数字人文", "人文计算", "计算人文", "数字人文研究", "数字学术", "数字转向",
    "数字记忆", "数字叙事", "数字文化", "文化遗产", "数字典藏", "数位典藏", "特藏",
    "数字保存", "数字保护", "数字化保护", "数字修复", "GLAM", "博物馆", "档案馆",
    "文物", "非物质文化遗产", "非遗", "计量文体", "计量史学",
]

#: 「数字人文」表：仅领域词，任一命中即算（计算方法词不在此列，见模块docstring）
KW_DIGITAL_HUMANITIES: List[str] = DH_FIELD

#: 「历史学+AI」表：历史词 + 计算方法，需两侧共现才算
KW_HISTORY_AI: List[str] = HISTORY + AI_COMPUTE


# --------------------------------------------------------------------------
# 命中判定
# --------------------------------------------------------------------------

def matchText(article: Article) -> str:
    """把参与匹配的字段拼成一段文本：标题 / 摘要 / 关键词 / 栏目。"""
    return " ".join([
        article.title or "",
        article.abstract or "",
        article.keywords or "",
        article.section or "",
    ])


def _hits(text: str, keywords: Iterable[str]) -> List[str]:
    return [kw for kw in keywords if kw in text]


def dhHits(article: Article) -> List[str]:
    """命中的「数字人文」领域词（DH_FIELD 任一命中即返回；空列表表示未命中）。

    计算方法词（AI_COMPUTE）不在此列：它们只在「历史+AI 共现」时计入，
    避免图情刊里「纯 AI 方法」论文被误收为数字人文。
    """
    return _hits(matchText(article), KW_DIGITAL_HUMANITIES)


def historyAiHits(article: Article) -> List[str]:
    """命中的「历史学+AI」关键词，采用共现判定。

    仅当 HISTORY 与 AI_COMPUTE **各至少命中一个**时，返回两侧命中词之和；
    否则返回空列表。这样「纯历史（无计算）」与「纯 AI（无历史）」都不误收。
    """
    text = matchText(article)
    hist = _hits(text, HISTORY)
    ai = _hits(text, AI_COMPUTE)
    if hist and ai:
        return hist + ai
    return []


def tagArticles(articles: Sequence[Article]) -> Sequence[Article]:
    """就地给每篇文章打 dhMatched / histAiMatched 双标签，返回同一列表。"""
    for article in articles:
        article.dhMatched = dhHits(article)
        article.histAiMatched = historyAiHits(article)
    return articles


def isDh(article: Article) -> bool:
    """是否算 DH 散篇：命中 DH_FIELD 领域词，或命中历史学+AI 共现。

    纯计算方法词（无领域词、无历史共现）不算 DH。
    """
    return bool(article.dhMatched or article.histAiMatched)


__all__ = [
    "AI_COMPUTE",
    "DH_FIELD",
    "HISTORY",
    "KW_DIGITAL_HUMANITIES",
    "KW_HISTORY_AI",
    "dhHits",
    "historyAiHits",
    "isDh",
    "matchText",
    "tagArticles",
]
