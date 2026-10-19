"""分块策略：保持语义完整的前提下切成大小均匀的片段。

优先按文档自身的章节切分；单节过长时再按句子滑动窗口切分，
并保留上下文重叠，避免政策条款被截断导致检索歧义。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..nlp import split_sentences
from .loaders import ParsedSection


@dataclass
class ChunkDraft:
    content: str
    section: str = ""
    page_no: int | None = None
    row_ref: str = ""
    meta: dict = field(default_factory=dict)


def _pack(sentences: list[str], size: int, overlap: int) -> list[str]:
    """把句子贪心装箱成不超过 size 字符的窗口，窗口之间保留 overlap 字符重叠。"""
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for sent in sentences:
        s_len = len(sent)
        if buf and buf_len + s_len > size:
            chunks.append("".join(buf).strip())
            # 构造重叠：从尾部回取
            tail: list[str] = []
            tail_len = 0
            for s in reversed(buf):
                if tail_len + len(s) > overlap:
                    break
                tail.insert(0, s)
                tail_len += len(s)
            buf = tail
            buf_len = tail_len
        buf.append(sent)
        buf_len += s_len

    if buf:
        chunks.append("".join(buf).strip())
    return [c for c in chunks if c]


def chunk_sections(
    sections: list[ParsedSection],
    *,
    chunk_size: int = 600,
    overlap: int = 100,
    min_chunk: int = 30,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for sec in sections:
        text = (sec.text or "").strip()
        if not text:
            continue

        if len(text) <= chunk_size:
            if len(text) >= min_chunk or drafts:
                drafts.append(
                    ChunkDraft(
                        content=text,
                        section=sec.title or "",
                        page_no=sec.page_no,
                        row_ref=sec.row_ref,
                        meta=dict(sec.meta or {}),
                    )
                )
            continue

        sentences = split_sentences(text)
        if not sentences:
            sentences = [text]
        for piece in _pack(sentences, chunk_size, overlap):
            if len(piece) < min_chunk and drafts:
                continue
            drafts.append(
                ChunkDraft(
                    content=piece,
                    section=sec.title or "",
                    page_no=sec.page_no,
                    row_ref=sec.row_ref,
                    meta=dict(sec.meta or {}),
                )
            )
    return drafts