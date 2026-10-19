"""向量库与关键词索引。

实现说明：当前使用「数据库持久化 + 内存索引」方案——
分块向量以二进制形式保存在 kb_chunks.embedding，检索时在进程内构建
numpy 矩阵做余弦相似度，并同步构建 BM25 词法索引。

该方案零外部服务依赖，适合院系级数据量（数万条分块以内，单次检索 <100ms）。
如需扩展到更大规模，只需实现本文件中的 `KnowledgeIndex` 同名方法，
替换为 pgvector / Milvus / Elasticsearch 即可，检索层与智能体层无需改动。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import KbChunk, KbDocument


@dataclass
class IndexEntry:
    chunk_id: int
    document_id: int
    content: str
    tokens: list[str]
    vector: np.ndarray | None
    section: str = ""
    page_no: int | None = None
    row_ref: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    # 文档级元数据（冗余存放，避免检索时反复联表）
    doc_title: str = ""
    doc_type: str = ""
    year: int | None = None
    competition_id: int | None = None
    competition_name: str = ""
    issuing_body: str = ""
    doc_no: str = ""
    source_path: str = ""
    source_url: str = ""


class KnowledgeIndex:
    """知识库检索索引（线程安全的懒加载单例）。"""

    _lock = threading.RLock()
    _instance: "KnowledgeIndex | None" = None

    def __init__(self) -> None:
        self.entries: list[IndexEntry] = []
        self.emb_matrix: np.ndarray | None = None
        self.bm25: BM25Okapi | None = None
        self._signature: tuple[int, int] = (-1, -1)
        self.dim: int = 0

    # ---------- 单例 ----------
    @classmethod
    def instance(cls) -> "KnowledgeIndex":
        with cls._lock:
            if cls._instance is None:
                cls._instance = KnowledgeIndex()
            return cls._instance

    @classmethod
    def invalidate(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance._signature = (-1, -1)

    # ---------- 加载 ----------
    def _current_signature(self, db: Session) -> tuple[int, int]:
        row = db.execute(select(func.count(KbChunk.id), func.coalesce(func.max(KbChunk.id), 0))).one()
        return int(row[0] or 0), int(row[1] or 0)

    def ensure_loaded(self, db: Session, *, force: bool = False) -> None:
        sig = self._current_signature(db)
        with self._lock:
            if not force and sig == self._signature and self.entries:
                return
            self._build(db, sig)

    def _build(self, db: Session, sig: tuple[int, int]) -> None:
        rows = db.execute(
            select(KbChunk, KbDocument)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
            .where(KbDocument.status == "已入库")
            .order_by(KbChunk.document_id, KbChunk.chunk_index)
        ).all()

        entries: list[IndexEntry] = []
        corpus: list[list[str]] = []
        dim = 0

        for chunk, doc in rows:
            vec = None
            if chunk.embedding:
                try:
                    vec = np.frombuffer(chunk.embedding, dtype=np.float32)
                    dim = max(dim, vec.shape[0])
                except ValueError:
                    vec = None
            tokens = (chunk.tokens or "").split()
            entries.append(
                IndexEntry(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    content=chunk.content,
                    tokens=tokens,
                    vector=vec,
                    section=chunk.section or "",
                    page_no=chunk.page_no,
                    row_ref=chunk.row_ref or "",
                    meta=chunk.meta or {},
                    doc_title=doc.title,
                    doc_type=doc.doc_type,
                    year=doc.year,
                    competition_id=doc.competition_id,
                    competition_name=doc.competition_name or "",
                    issuing_body=doc.issuing_body or "",
                    doc_no=doc.doc_no or "",
                    source_path=doc.source_path or "",
                    source_url=doc.source_url or "",
                )
            )
            corpus.append(tokens)

        if dim and any(e.vector is not None for e in entries):
            matrix = np.zeros((len(entries), dim), dtype=np.float32)
            for i, entry in enumerate(entries):
                if entry.vector is not None and entry.vector.shape[0] == dim:
                    matrix[i] = entry.vector
            # 统一做 L2 归一化，余弦相似度即点积
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.emb_matrix = matrix / norms
        else:
            self.emb_matrix = None

        self.entries = entries
        self.dim = dim
        self.bm25 = BM25Okapi(corpus) if corpus else None
        self._signature = sig

    # ---------- 检索 ----------
    def search_vector(self, query_vec: list[float], top_n: int) -> list[tuple[int, float]]:
        """返回 (entry 下标, 余弦相似度) 列表。"""
        matrix = self.emb_matrix
        if matrix is None or not query_vec:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        if q.shape[0] != matrix.shape[1]:
            return []
        n = float(np.linalg.norm(q))
        if n <= 1e-9:
            return []
        sims = matrix @ (q / n)
        top_n = min(top_n, sims.shape[0])
        idx = np.argpartition(-sims, top_n - 1)[:top_n] if top_n < sims.shape[0] else np.arange(sims.shape[0])
        pairs = [(int(i), float(sims[i])) for i in idx]
        pairs.sort(key=lambda x: -x[1])
        return pairs

    def search_keyword(self, query_tokens: list[str], top_n: int) -> list[tuple[int, float]]:
        if self.bm25 is None or not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)
        arr = np.asarray(scores, dtype=np.float32)
        if arr.size == 0:
            return []
        top_n = min(top_n, arr.shape[0])
        idx = np.argpartition(-arr, top_n - 1)[:top_n] if top_n < arr.shape[0] else np.arange(arr.shape[0])
        pairs = [(int(i), float(arr[i])) for i in idx]
        pairs.sort(key=lambda x: -x[1])
        return pairs

    def stats(self) -> dict[str, Any]:
        dims = sorted({e.vector.shape[0] for e in self.entries if e.vector is not None})
        return {
            "chunks": len(self.entries),
            "documents": len({e.document_id for e in self.entries}),
            "has_vector": self.emb_matrix is not None,
            "vector_dim": dims[0] if dims else 0,
            "bm25_ready": self.bm25 is not None,
        }