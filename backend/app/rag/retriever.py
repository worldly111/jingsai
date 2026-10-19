"""混合检索：向量召回 + 关键词召回 + 规则重排，输出可直接溯源的证据片段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..llm import get_embedder
from ..nlp import tokenize, truncate
from .vectorstore import IndexEntry, KnowledgeIndex


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    doc_type: str
    content: str
    score: float = 0.0
    vector_score: float = 0.0
    keyword_score: float = 0.0
    section: str = ""
    page_no: int | None = None
    row_ref: str = ""
    year: int | None = None
    competition_id: int | None = None
    competition_name: str = ""
    issuing_body: str = ""
    doc_no: str = ""
    source_path: str = ""
    source_url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def snippet(self, limit: int = 260) -> str:
        return truncate(self.content.replace("\n", " "), limit)

    def citation(self, order: int) -> dict[str, Any]:
        """构造引用溯源信息，供前端展示与导出。"""
        location = ""
        if self.section:
            location = self.section
        if self.page_no:
            location = f"{location} 第{self.page_no}页".strip()
        if self.row_ref:
            location = f"{location} {self.row_ref}".strip()
        return {
            "index": order,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "title": self.document_title,
            "doc_type": self.doc_type,
            "doc_no": self.doc_no,
            "issuing_body": self.issuing_body,
            "year": self.year,
            "competition_name": self.competition_name,
            "location": location,
            "snippet": self.snippet(),
            "score": round(self.score, 4),
            "source_path": self.source_path,
            "source_url": self.source_url,
        }


def _entry_to_chunk(entry: IndexEntry) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=entry.chunk_id,
        document_id=entry.document_id,
        document_title=entry.doc_title,
        doc_type=entry.doc_type,
        content=entry.content,
        section=entry.section,
        page_no=entry.page_no,
        row_ref=entry.row_ref,
        year=entry.year,
        competition_id=entry.competition_id,
        competition_name=entry.competition_name,
        issuing_body=entry.issuing_body,
        doc_no=entry.doc_no,
        source_path=entry.source_path,
        source_url=entry.source_url,
        meta=entry.meta or {},
    )


class HybridRetriever:
    """知识库检索器。

    打分 = 向量权重 × 归一化余弦 + 关键词权重 × 归一化 BM25 + 规则加权项。
    规则加权项用于修正词法/语义都容易漏掉的情况：关键词原样命中、年份一致、
    标题命中、条款编号命中等。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.index = KnowledgeIndex.instance()

    # ---------- 主入口 ----------
    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        recall_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        if not query or not query.strip():
            return []

        self.index.ensure_loaded(self.db)
        if not self.index.entries:
            return []

        top_k = top_k or settings.rag_top_k
        recall_k = recall_k or settings.rag_recall_k

        query_tokens = tokenize(query)
        query_vec: list[float] = []
        try:
            embedder = get_embedder()
            query_vec = embedder.embed_query(query)
        except Exception:  # noqa: BLE001 - 向量服务异常时退化为纯关键词检索
            query_vec = []

        vec_pairs = self.index.search_vector(query_vec, recall_k)
        kw_pairs = self.index.search_keyword(query_tokens or [query], recall_k)

        vec_scores = {i: s for i, s in vec_pairs}
        kw_scores = {i: s for i, s in kw_pairs}

        # 归一化
        vec_norm = max((s for _, s in vec_pairs), default=0.0)
        kw_norm = max((s for _, s in kw_pairs), default=0.0)

        vw = settings.rag_vector_weight
        kw = settings.rag_keyword_weight
        total = vw + kw or 1.0
        vw, kw = vw / total, kw / total

        candidates = set(vec_scores) | set(kw_scores)
        results: list[RetrievedChunk] = []
        q_lower = query.lower()

        for idx in candidates:
            entry = self.index.entries[idx]
            if not self._pass_filter(entry, filters):
                continue

            v = (vec_scores.get(idx, 0.0) + 1.0) / 2.0 if idx in vec_scores else 0.0
            k = (kw_scores.get(idx, 0.0) / kw_norm) if idx in kw_scores and kw_norm > 0 else 0.0
            if idx in vec_scores and vec_norm > 0:
                v = max(0.0, min(1.0, v))
            score = vw * v + kw * k
            score += self._rule_bonus(entry, query_tokens, q_lower)

            if score < settings.rag_min_score:
                continue

            chunk = _entry_to_chunk(entry)
            chunk.vector_score = round(v, 4)
            chunk.keyword_score = round(k, 4)
            chunk.score = score
            results.append(chunk)

        results.sort(key=lambda c: -c.score)
        return results[:top_k]

    # ---------- 内部 ----------
    @staticmethod
    def _pass_filter(entry: IndexEntry, filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        doc_type = filters.get("doc_type")
        if doc_type:
            allowed = {doc_type} if isinstance(doc_type, str) else set(doc_type)
            if entry.doc_type not in allowed:
                return False
        if filters.get("year") and entry.year != filters["year"]:
            return False
        if filters.get("competition_id") and entry.competition_id != filters["competition_id"]:
            return False
        doc_ids = filters.get("document_ids")
        if doc_ids and entry.document_id not in set(doc_ids):
            return False
        return True

    @staticmethod
    def _rule_bonus(entry: IndexEntry, query_tokens: list[str], q_lower: str) -> float:
        bonus = 0.0
        content_lower = entry.content.lower()

        # 关键短语原样命中（用户直接引用了通知原文）
        if 4 <= len(q_lower) <= 40 and q_lower in content_lower:
            bonus += 0.18

        # 标题 / 章节命中
        if entry.doc_title and any(t and t in entry.doc_title for t in query_tokens[:8]):
            bonus += 0.08
        if entry.section and any(t and t in entry.section for t in query_tokens[:8]):
            bonus += 0.06

        # 年份一致（"2025年蓝桥杯报名费" 通常指 2025 届）
        for year in ("2023", "2024", "2025", "2026", "2027"):
            if year in q_lower and year in content_lower:
                bonus += 0.05
                break

        # 条款编号命中（第X条 / 第X章）
        for token in query_tokens:
            if token.startswith("第") and token.endswith(("条", "章", "款")) and token in content_lower:
                bonus += 0.1
                break

        # 过短片段信息量不足，轻微降权
        if len(entry.content) < 25:
            bonus -= 0.04

        return bonus

    def retrieve_multi(
        self,
        queries: list[str],
        *,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """多查询召回后去重合并（用于把用户问题扩展为若干子查询）。"""
        merged: dict[int, RetrievedChunk] = {}
        for q in queries:
            for chunk in self.retrieve(q, top_k=(top_k or settings.rag_top_k) * 2, filters=filters):
                prev = merged.get(chunk.chunk_id)
                if prev is None or chunk.score > prev.score:
                    merged[chunk.chunk_id] = chunk
        out = sorted(merged.values(), key=lambda c: -c.score)
        return out[: (top_k or settings.rag_top_k)]

    def stats(self) -> dict[str, Any]:
        self.index.ensure_loaded(self.db)
        return self.index.stats()