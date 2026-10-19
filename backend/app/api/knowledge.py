"""知识库管理接口：上传、检索、重索引与原文下载。"""

from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.base import get_db
from ..db.models import Competition, KbChunk, KbDocument
from ..rag.ingest import delete_document, ingest_directory, ingest_file, reindex_document
from ..rag.loaders import SUPPORTED_SUFFIXES, load_document
from ..rag.retriever import HybridRetriever
from ..security import require

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _doc_row(doc: KbDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "doc_type": doc.doc_type,
        "year": doc.year,
        "competition_id": doc.competition_id,
        "competition_name": doc.competition_name,
        "issuing_body": doc.issuing_body,
        "doc_no": doc.doc_no,
        "effective_date": str(doc.effective_date) if doc.effective_date else "",
        "file_name": doc.file_name,
        "source_path": doc.source_path,
        "source_url": doc.source_url,
        "file_size": doc.file_size,
        "tags": doc.tags or [],
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "char_count": doc.char_count,
        "error_msg": doc.error_msg,
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
    }


@router.get("/knowledge/stats", dependencies=[Depends(require("knowledge.read"))])
def knowledge_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    retriever = HybridRetriever(db)
    stats = retriever.stats()
    by_type = db.execute(
        select(KbDocument.doc_type, func.count(KbDocument.id)).group_by(KbDocument.doc_type)
    ).all()
    stats["by_type"] = [{"doc_type": t or "其他", "count": int(c)} for t, c in by_type]
    stats["failed"] = int(db.query(KbDocument).filter(KbDocument.status != "已入库").count())
    stats["supported_formats"] = sorted(SUPPORTED_SUFFIXES)
    return stats


@router.get("/knowledge/documents", dependencies=[Depends(require("knowledge.read"))])
def list_documents(
    db: Session = Depends(get_db),
    keyword: str = "",
    doc_type: str = "",
    year: int | None = None,
    status: str = "",
) -> dict[str, Any]:
    stmt = select(KbDocument).order_by(desc(KbDocument.id))
    if keyword:
        stmt = stmt.where(KbDocument.title.like(f"%{keyword}%"))
    if doc_type:
        stmt = stmt.where(KbDocument.doc_type == doc_type)
    if year:
        stmt = stmt.where(KbDocument.year == year)
    if status:
        stmt = stmt.where(KbDocument.status == status)
    rows = db.execute(stmt).scalars().all()
    return {"items": [_doc_row(d) for d in rows], "total": len(rows)}


@router.get("/knowledge/documents/{document_id}", dependencies=[Depends(require("knowledge.read"))])
def document_detail(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    doc = db.get(KbDocument, document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    chunks = db.execute(
        select(KbChunk).where(KbChunk.document_id == document_id).order_by(KbChunk.chunk_index)
    ).scalars().all()
    return {
        "document": _doc_row(doc),
        "chunks": [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "section": c.section,
                "page_no": c.page_no,
                "row_ref": c.row_ref,
                "char_count": c.char_count,
                "has_vector": c.embedding is not None,
            }
            for c in chunks
        ],
    }


@router.post("/knowledge/upload", dependencies=[Depends(require("knowledge.write"))])
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(""),
    year: int | None = Form(None),
    competition_id: int | None = Form(None),
    issuing_body: str = Form(""),
    doc_no: str = Form(""),
    source_url: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"不支持的文件格式 {suffix or '（无后缀）'}，支持：{' / '.join(sorted(SUPPORTED_SUFFIXES))}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件超过 50MB 限制")
    if not data:
        raise HTTPException(400, "文件为空")

    safe_name = re.sub(r"[\\/:*?\"<>|]+", "_", Path(file.filename or f"upload{suffix}").name)
    target_dir = settings.upload_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    if target.exists():
        target = target_dir / f"{target.stem}-{datetime.now():%Y%m%d%H%M%S}{suffix}"
    target.write_bytes(data)

    comp_name = ""
    if competition_id:
        comp = db.get(Competition, competition_id)
        comp_name = comp.name if comp else ""

    meta: dict[str, Any] = {
        "doc_type": doc_type or None,
        "year": year,
        "issuing_body": issuing_body,
        "doc_no": doc_no,
        "source_url": source_url,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
    }
    if comp_name:
        meta["competition_name"] = comp_name
    meta = {k: v for k, v in meta.items() if v not in (None, "", [])}
    result = ingest_file(db, target, meta=meta)
    db.commit()
    return {
        "ok": result.status == "已入库",
        "document_id": result.document_id,
        "title": result.title,
        "status": result.status,
        "chunks": result.chunk_count,
        "chars": result.char_count,
        "message": result.message or result.status,
    }


@router.post("/review/extract", dependencies=[Depends(require("review.use"))])
async def extract_material(file: UploadFile = File(...)) -> dict[str, Any]:
    """解析待检查的项目材料，仅提取文本，不写入知识库。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"不支持的文件格式 {suffix or '（无后缀）'}，支持：{' / '.join(sorted(SUPPORTED_SUFFIXES))}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件超过 50MB 限制")
    if not data:
        raise HTTPException(400, "文件为空")

    tmp_path: Path | None = None
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.upload_path) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        doc = load_document(tmp_path)
    except Exception as exc:  # noqa: BLE001 - 解析失败需要返回可读原因
        raise HTTPException(400, f"文件解析失败：{exc}") from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    text = doc.text.strip()
    return {
        "ok": True,
        "title": doc.title or Path(file.filename or "").stem,
        "file_name": file.filename,
        "text": text[:200000],
        "char_count": len(text),
        "section_count": len(doc.sections),
    }


@router.post("/knowledge/reindex", dependencies=[Depends(require("knowledge.write"))])
def reindex_all(db: Session = Depends(get_db)) -> dict[str, Any]:
    results = ingest_directory(db)
    db.commit()
    return {
        "ok": True,
        "total": len(results),
        "succeeded": sum(1 for r in results if r.status == "已入库"),
        "skipped": sum(1 for r in results if r.skipped),
        "items": [
            {"document_id": r.document_id, "title": r.title, "status": r.status,
             "chunks": r.chunk_count, "message": r.message}
            for r in results
        ],
    }


@router.post("/knowledge/documents/{document_id}/reindex", dependencies=[Depends(require("knowledge.write"))])
def reindex_one(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        result = reindex_document(db, document_id)
        db.commit()
    except (ValueError, FileNotFoundError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": result.status == "已入库", "document_id": result.document_id, "title": result.title,
        "status": result.status, "chunks": result.chunk_count, "message": result.message,
    }


@router.delete("/knowledge/documents/{document_id}", dependencies=[Depends(require("knowledge.write"))])
def remove_document(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not delete_document(db, document_id):
        raise HTTPException(404, "文档不存在")
    db.commit()
    return {"ok": True}


@router.get("/knowledge/search", dependencies=[Depends(require("knowledge.read"))])
def search_knowledge(q: str, top_k: int = 6, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not q.strip():
        return {"items": []}
    chunks = HybridRetriever(db).retrieve(q, top_k=min(max(top_k, 1), 20))
    return {
        "items": [
            {
                **c.citation(i),
                "content": c.content,
                "vector_score": c.vector_score,
                "keyword_score": c.keyword_score,
            }
            for i, c in enumerate(chunks, start=1)
        ]
    }


@router.get("/knowledge/documents/{document_id}/file", dependencies=[Depends(require("knowledge.read"))])
def download_source(document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    doc = db.get(KbDocument, document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    path = Path(doc.source_path or "").resolve()
    allowed = [settings.knowledge_path.resolve(), settings.upload_path.resolve()]
    if not path.exists() or not any(path.is_relative_to(root) for root in allowed):
        raise HTTPException(404, "原始文件不存在或不在允许的目录内")
    return FileResponse(path, filename=doc.file_name or path.name)
