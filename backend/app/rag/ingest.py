"""知识库导入流水线：文件 → 解析 → 分块 → 向量化 → 入库。

新增赛事、新增年度政策文件只需要把文件放进 data/knowledge 目录后重新导入，
知识不会固化在代码中。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Competition, KbChunk, KbDocument
from ..llm import get_embedder
from ..nlp import tokenize
from .chunking import chunk_sections
from .loaders import SUPPORTED_SUFFIXES, load_document
from .vectorstore import KnowledgeIndex


@dataclass
class IngestResult:
    document_id: int
    title: str
    chunk_count: int
    char_count: int
    status: str
    message: str = ""
    skipped: bool = False


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def infer_metadata(path: Path) -> dict[str, Any]:
    """从文件名推断文档类型、年份等元数据，减少人工录入。

    命名建议：`2025-蓝桥杯-报名通知.pdf`、`学科竞赛管理办法.txt`。
    """
    stem = path.stem
    meta: dict[str, Any] = {"title": stem, "doc_type": "其他", "year": None}

    for part in stem.replace("_", "-").split("-"):
        part = part.strip()
        if part.isdigit() and len(part) == 4:
            meta["year"] = int(part)
            break

    rules = [
        ("竞赛规程", ("规程", "章程", "赛事指南", "参赛指南", "比赛规则", "竞赛规则")),
        ("管理制度", ("管理办法", "管理制度", "实施细则", "经费管理", "差旅", "报销")),
        ("获奖名单", ("获奖名单", "获奖情况", "获奖统计", "成绩", "公示")),
        ("评审标准", ("评审", "评分标准", "评分细则", "评价指标")),
        ("通知公告", ("通知", "公告", "征集", "报名")),
    ]
    for doc_type, keywords in rules:
        if any(k in stem for k in keywords):
            meta["doc_type"] = doc_type
            break

    return meta


def _resolve_competition(db: Session, doc_meta: dict[str, Any], title: str) -> tuple[int | None, str]:
    comp_id = doc_meta.get("competition_id")
    if comp_id:
        comp = db.get(Competition, int(comp_id))
        return (comp.id, comp.name) if comp else (None, "")
    name = (doc_meta.get("competition_name") or "").strip()
    if not name:
        # 用标题去匹配已知赛事
        for comp in db.execute(select(Competition)).scalars():
            if comp.name and comp.name in title:
                return comp.id, comp.name
            if comp.short_name and len(comp.short_name) >= 3 and comp.short_name in title:
                return comp.id, comp.name
        return None, ""
    comp = db.execute(select(Competition).where(Competition.name == name)).scalars().first()
    return (comp.id, comp.name) if comp else (None, name)


def ingest_file(
    db: Session,
    path: str | Path,
    *,
    meta: dict[str, Any] | None = None,
    replace_existing: bool = True,
) -> IngestResult:
    p = Path(path)
    provided_meta = dict(meta or {})
    meta = {**infer_metadata(p), **provided_meta}

    digest = file_hash(p)

    existing = db.execute(select(KbDocument).where(KbDocument.file_hash == digest)).scalars().first()
    if existing:
        if not replace_existing:
            return IngestResult(
                document_id=existing.id,
                title=existing.title,
                chunk_count=existing.chunk_count,
                char_count=existing.char_count,
                status=existing.status,
                message="相同内容的文档已存在，已跳过",
                skipped=True,
            )
        delete_document(db, existing.id)

    doc = KbDocument(
        title=str(meta.get("title") or p.stem),
        doc_type=str(meta.get("doc_type") or "其他"),
        year=meta.get("year"),
        issuing_body=str(meta.get("issuing_body") or ""),
        doc_no=str(meta.get("doc_no") or ""),
        effective_date=_to_date(meta.get("effective_date")),
        file_name=p.name,
        source_path=str(p.resolve()),
        source_url=str(meta.get("source_url") or ""),
        mime_type=p.suffix.lower(),
        file_size=p.stat().st_size,
        file_hash=digest,
        tags=list(meta.get("tags") or []),
        status="待处理",
    )
    doc.competition_id, doc.competition_name = _resolve_competition(db, meta, doc.title)
    db.add(doc)
    db.flush()

    try:
        parsed = load_document(p)
        front_matter = parsed.meta.get("front_matter") or {}
        if front_matter:
            merged = {**front_matter, **provided_meta}
            doc.title = str(merged.get("title") or doc.title)
            doc.doc_type = str(merged.get("doc_type") or doc.doc_type)
            if merged.get("year"):
                doc.year = int(merged["year"])
            doc.issuing_body = str(merged.get("issuing_body") or doc.issuing_body)
            doc.doc_no = str(merged.get("doc_no") or doc.doc_no)
            doc.effective_date = _to_date(merged.get("effective_date")) or doc.effective_date
            doc.source_url = str(merged.get("source_url") or doc.source_url)
            doc.tags = list(merged.get("tags") or doc.tags)
            doc.competition_id, doc.competition_name = _resolve_competition(db, merged, doc.title)
            db.flush()
        drafts = chunk_sections(
            parsed.sections,
            chunk_size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )
        if not drafts:
            doc.status = "失败"
            doc.error_msg = "未能从文档中解析出可用文本（可能是扫描版 PDF，需要 OCR 后再导入）"
            db.flush()
            return IngestResult(doc.id, doc.title, 0, 0, "失败", doc.error_msg)

        embedder = get_embedder()
        texts = [d.content for d in drafts]
        vectors: list[list[float]] = []
        emb_model = ""
        try:
            vectors = embedder.embed_documents(texts)
            emb_model = getattr(embedder, "model", getattr(embedder, "label", ""))
        except Exception as exc:  # noqa: BLE001 - 向量服务不可用时仍保留文本，检索退化为关键词模式
            vectors = []
            doc.error_msg = f"向量化失败，已按关键词检索模式入库：{exc}"

        import numpy as np

        for i, draft in enumerate(drafts):
            vec = vectors[i] if i < len(vectors) else None
            blob = None
            dim = 0
            if vec:
                arr = np.asarray(vec, dtype=np.float32)
                blob = arr.tobytes()
                dim = int(arr.shape[0])
            db.add(
                KbChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=draft.content,
                    section=draft.section or "",
                    page_no=draft.page_no,
                    row_ref=draft.row_ref or "",
                    char_count=len(draft.content),
                    tokens=" ".join(tokenize(draft.content)),
                    embedding=blob,
                    embedding_model=emb_model,
                    embedding_dim=dim,
                    meta=draft.meta or {},
                )
            )

        doc.chunk_count = len(drafts)
        doc.char_count = parsed.char_count
        doc.status = "已入库"
        db.flush()
        KnowledgeIndex.invalidate()
        return IngestResult(doc.id, doc.title, doc.chunk_count, doc.char_count, "已入库", doc.error_msg)

    except Exception as exc:  # noqa: BLE001
        doc.status = "失败"
        doc.error_msg = str(exc)[:500]
        db.flush()
        return IngestResult(doc.id, doc.title, 0, 0, "失败", f"导入失败：{exc}")


def ingest_directory(db: Session, directory: str | Path | None = None, *, recursive: bool = True) -> list[IngestResult]:
    root = Path(directory) if directory else settings.knowledge_path
    if not root.exists():
        return []
    pattern = "**/*" if recursive else "*"
    results: list[IngestResult] = []
    for p in sorted(root.glob(pattern)):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        results.append(ingest_file(db, p))
    return results


def reindex_document(db: Session, document_id: int) -> IngestResult:
    doc = db.get(KbDocument, document_id)
    if not doc:
        raise ValueError(f"知识库文档不存在：{document_id}")
    path = Path(doc.source_path)
    if not path.exists():
        raise FileNotFoundError(f"原始文件已不存在：{path}")
    meta = {
        "title": doc.title,
        "doc_type": doc.doc_type,
        "year": doc.year,
        "issuing_body": doc.issuing_body,
        "doc_no": doc.doc_no,
        "competition_id": doc.competition_id,
        "source_url": doc.source_url,
        "tags": doc.tags,
    }
    db.delete(doc)
    db.flush()
    return ingest_file(db, path, meta=meta)


def delete_document(db: Session, document_id: int) -> bool:
    doc = db.get(KbDocument, document_id)
    if not doc:
        return False
    db.delete(doc)
    db.flush()
    KnowledgeIndex.invalidate()
    return True


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None