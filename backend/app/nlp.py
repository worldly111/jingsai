"""中文文本处理工具：分词、句子切分、字符 n-gram。

RAG 的关键词检索与离线向量化共用这里的能力，避免多处重复实现。
"""

from __future__ import annotations

import logging
import re

import jieba

jieba.setLogLevel(logging.INFO)

# 常见停用词（中文虚词 + 英文功能词），用于提升关键词检索的信噪比
STOPWORDS: set[str] = {
    "的", "了", "和", "是", "在", "我", "有", "就", "不", "人", "都", "一", "一个", "上", "也",
    "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "与",
    "及", "或", "等", "对", "从", "为", "以", "被", "把", "并", "而", "但", "如果", "因为", "所以",
    "可以", "需要", "进行", "通过", "以及", "其中", "对于", "关于", "根据", "按照", "相关", "有关",
    "什么", "怎么", "如何", "哪些", "哪个", "多少", "请", "问", "吗", "呢", "吧", "啊",
    "a", "an", "the", "is", "are", "was", "were", "of", "to", "in", "on", "for", "and", "or",
    "how", "what", "which", "when", "where", "who", "why", "do", "does", "did", "can", "could",
}

_PUNCT_RE = re.compile(r"[\s\u3000!-/:-@\[-`{-~！-＠［-｀｛-～、。，；：？！""''（）《》【】…—·]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；!?;\n])")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """jieba 分词 + 停用词过滤；英文与数字按原样保留并转小写。"""
    if not text:
        return []
    cleaned = _PUNCT_RE.sub(" ", text)
    tokens: list[str] = []
    for word in jieba.lcut(cleaned):
        w = word.strip().lower()
        if not w or len(w) == 1 and not w.isdigit() and not _is_cjk(w):
            # 丢弃单字（中文单字噪声大），保留单个数字
            continue
        if not keep_stopwords and w in STOPWORDS:
            continue
        tokens.append(w)
    return tokens


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def char_ngrams(text: str, n: int = 2) -> list[str]:
    """字符 n-gram，用于离线哈希向量，弥补分词粒度不足。"""
    seq = _PUNCT_RE.sub("", text or "").lower()
    if len(seq) < n:
        return [seq] if seq else []
    return [seq[i : i + n] for i in range(len(seq) - n + 1)]


def split_sentences(text: str, *, min_len: int = 8) -> list[str]:
    """按中文标点切句，用于抽取式回答与证据片段定位。"""
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(normalize(text)) if p and p.strip()]
    out: list[str] = []
    for p in parts:
        if len(p) >= min_len:
            out.append(p)
        elif out:
            out[-1] = f"{out[-1]} {p}"
        elif p:
            out.append(p)
    return out


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - len(suffix)] + suffix


def mask_sensitive(text: str) -> str:
    """对身份证号等做简单脱敏（发票/票据备注中可能出现）。"""
    if not text:
        return ""
    return re.sub(r"\b(\d{6})\d{8}(\d{3}[\dXx])\b", r"\1********\2", text)