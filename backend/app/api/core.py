"""系统元信息、智能体运行与会话接口。"""

from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..agents import runner
from ..agents.graphs import GRAPH_SPECS
from ..config import settings
from ..db.base import get_db
from ..db.models import AgentRunLog, ChatMessage, ChatSession, Competition, KbDocument, QaLog
from ..llm import get_embedder, get_llm
from ..security import (
    AGENT_PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    current_role,
    ensure_agent_access,
    ensure_session_access,
    has_permission,
    require,
)

router = APIRouter()


def _owned_session(db: Session, session_id: int, role: str) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    ensure_session_access(session.user_role, role)
    return session


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None
    user_role: str = "学生"
    profile: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(BaseModel):
    title: str = "新会话"
    agent: str = "qa"
    user_role: str = "学生"
    user_ref: str = ""


class AgentRunRequest(BaseModel):
    question: str = ""
    profile: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: int | None = None
    user_role: str = "学生"


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    llm = get_llm()
    embedder = get_embedder()
    docs = int(db.scalar(select(KbDocument.id).limit(1)) is not None)
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "llm": {
            "provider": llm.provider,
            "model": getattr(llm, "model", "builtin"),
            "available": getattr(llm, "is_available", False),
        },
        "embedding": {
            "provider": getattr(embedder, "provider", "builtin"),
            "model": getattr(embedder, "model", ""),
            "dim": getattr(embedder, "dim", 0),
        },
        "knowledge_documents": int(db.query(KbDocument).count()),
        "competitions": int(db.query(Competition).count()),
        "agents": len(GRAPH_SPECS),
        "has_knowledge": docs,
    }


@router.get("/meta/agents")
def agent_list(role: str = Depends(current_role)) -> dict[str, Any]:
    items = [
        item for item in runner.agent_catalog()
        if has_permission(role, AGENT_PERMISSIONS.get(item["agent"], ""))
    ]
    return {"items": items, "problems": runner.validate_all(), "count": len(items)}


@router.get("/meta/agents/{agent}")
def agent_detail(agent: str, role: str = Depends(current_role)) -> dict[str, Any]:
    item = next((x for x in runner.agent_catalog() if x["agent"] == agent), None)
    if not item:
        raise HTTPException(404, f"未知智能体：{agent}")
    ensure_agent_access(agent, role)
    return item


@router.get("/meta/options")
def options(db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..db.models import Major, Registration, Student, Teacher

    comps = db.execute(select(Competition).order_by(Competition.name)).scalars().all()
    reg_years = sorted({int(y) for (y,) in db.execute(select(Registration.year).distinct()).all()})
    return {
        "competitions": [
            {"id": c.id, "name": c.name, "short_name": c.short_name, "level": c.level, "category": c.category}
            for c in comps
        ],
        "years": reg_years,
        "levels": ["国家级", "省级", "校级"],
        "categories": sorted({c.category for c in comps if c.category}),
        "majors": [m for (m,) in db.execute(select(Major.name).order_by(Major.name)).all()],
        "teachers": [t for (t,) in db.execute(select(Teacher.name).order_by(Teacher.name)).all()],
        "students": [s for (s,) in db.execute(select(Student.name).order_by(Student.name)).all()],
        "doc_types": ["通知公告", "竞赛规程", "管理制度", "获奖名单", "评审标准", "其他"],
        "user_roles": list(ROLES),
    }


@router.get("/meta/permissions")
def meta_permissions(role: str = Depends(current_role)) -> dict[str, Any]:
    return {
        "role": role,
        "roles": list(ROLES),
        "permissions": sorted(ROLE_PERMISSIONS[role]),
    }


# ============================================================
#  智能体运行
# ============================================================
@router.post("/agents/{agent}/run")
def run_agent(
    agent: str, body: AgentRunRequest, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    if agent not in GRAPH_SPECS:
        raise HTTPException(404, f"未知智能体：{agent}")
    ensure_agent_access(agent, role)
    session_id = body.session_id
    if session_id is not None:
        _owned_session(db, session_id, role)
    if body.question and session_id is None and agent in {"qa", "stats"}:
        session = runner.ensure_session(
            db, None, title=body.question[:40], agent=agent,
            user_ref=str(body.profile.get("student_no") or ""), user_role=role,
        )
        db.commit()
        session_id = session.id
    result = runner.run_agent(
        db, agent, question=body.question, profile=body.profile, payload=body.payload,
        session_id=session_id, user_role=role,
    )
    if session_id and body.question:
        runner.append_message(db, session_id, "user", body.question, payload=body.payload)
        runner.append_message(
            db, session_id, "assistant", result.get("answer") or "",
            citations=result.get("citations"), payload=result.get("structured"),
            agent_trace={"run_id": result.get("run_id"), "steps": result.get("steps")},
        )
        db.commit()
    result["session_id"] = session_id
    return result


@router.post("/agents/{agent}/stream")
def stream_agent(
    agent: str, body: AgentRunRequest, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> StreamingResponse:
    if agent not in GRAPH_SPECS:
        raise HTTPException(404, f"未知智能体：{agent}")
    ensure_agent_access(agent, role)
    session_id = body.session_id
    if session_id is not None:
        _owned_session(db, session_id, role)
    if body.question and session_id is None:
        session = runner.ensure_session(db, None, title=body.question[:40], agent=agent, user_role=role)
        db.commit()
        session_id = session.id

    def event_stream() -> Iterator[str]:
        final: dict[str, Any] | None = None
        try:
            for event in runner.iter_agent(
                db, agent, question=body.question, profile=body.profile, payload=body.payload,
                session_id=session_id, user_role=role,
            ):
                if event.get("type") == "result":
                    final = event
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        if final and session_id and body.question:
            runner.append_message(db, session_id, "user", body.question, payload=body.payload)
            runner.append_message(
                db, session_id, "assistant", final.get("answer") or "",
                citations=final.get("citations"), payload=final.get("structured"),
                agent_trace={"run_id": final.get("run_id"), "steps": final.get("steps")},
            )
            db.commit()
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


# ============================================================
#  QA 会话
# ============================================================
@router.post("/qa/ask")
def qa_ask(
    body: AskRequest, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    ensure_agent_access("qa", role)
    session_id = body.session_id
    if not session_id:
        session = runner.ensure_session(db, None, title=body.question[:40], agent="qa", user_role=role)
        db.commit()
        session_id = session.id
    _owned_session(db, session_id, role)
    runner.append_message(db, session_id, "user", body.question, payload=body.payload)
    db.commit()
    result = runner.run_agent(
        db, "qa", question=body.question, profile=body.profile, payload=body.payload,
        session_id=session_id, user_role=role,
    )
    runner.append_message(
        db, session_id, "assistant", result.get("answer") or "",
        citations=result.get("citations"), payload=result.get("structured"),
        agent_trace={"run_id": result.get("run_id"), "steps": result.get("steps")},
    )
    db.commit()
    result["session_id"] = session_id
    return result


@router.get("/qa/sessions")
def qa_sessions(
    db: Session = Depends(get_db), limit: int = 30,
    role: str = Depends(current_role),
) -> dict[str, Any]:
    stmt = select(ChatSession).order_by(desc(ChatSession.id)).limit(limit)
    if role != "管理员":
        stmt = stmt.where(ChatSession.user_role == role)
    rows = db.execute(stmt).scalars().all()
    items = []
    for s in rows:
        last = db.execute(
            select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(desc(ChatMessage.id)).limit(1)
        ).scalars().first()
        items.append({
            "id": s.id, "title": s.title, "agent": s.agent, "user_role": s.user_role,
            "created_at": s.created_at.isoformat() if s.created_at else "",
            "last_message": (last.content[:80] if last else ""),
        })
    return {"items": items}


@router.post("/qa/sessions")
def create_session(
    body: SessionCreate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    session = runner.ensure_session(
        db, None, title=body.title, agent=body.agent, user_ref=body.user_ref, user_role=role
    )
    db.commit()
    return {"id": session.id, "title": session.title, "agent": session.agent}


@router.get("/qa/sessions/{session_id}")
def session_detail(
    session_id: int, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    session = _owned_session(db, session_id, role)
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    ).scalars().all()
    return {
        "id": session.id, "title": session.title, "agent": session.agent, "user_role": session.user_role,
        "messages": [
            {
                "id": m.id, "role": m.role, "content": m.content, "citations": m.citations,
                "payload": m.payload, "agent_trace": m.agent_trace,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ],
    }


@router.delete("/qa/sessions/{session_id}")
def delete_session(
    session_id: int, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    session = _owned_session(db, session_id, role)
    db.delete(session)
    db.commit()
    return {"ok": True}


# ============================================================
#  运行日志 / 质检
# ============================================================
@router.get("/logs/runs", dependencies=[Depends(require("logs.view"))])
def run_logs(db: Session = Depends(get_db), agent: str = "", limit: int = 30) -> dict[str, Any]:
    stmt = select(AgentRunLog).order_by(desc(AgentRunLog.id)).limit(min(limit, 200))
    if agent:
        stmt = stmt.where(AgentRunLog.agent == agent)
    rows = db.execute(stmt).scalars().all()
    return {
        "items": [
            {
                "id": r.id, "run_id": r.run_id, "agent": r.agent, "status": r.status,
                "duration_ms": r.duration_ms, "summary": r.output_summary, "error": r.error,
                "input": r.input_payload,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]
    }


@router.get("/logs/qa", dependencies=[Depends(require("logs.view"))])
def qa_logs(db: Session = Depends(get_db), limit: int = 50) -> dict[str, Any]:
    rows = db.execute(select(QaLog).order_by(desc(QaLog.id)).limit(min(limit, 200))).scalars().all()
    return {
        "items": [
            {
                "id": r.id, "agent": r.agent, "question": r.question,
                "citation_count": len(r.citations or []), "used_knowledge": r.used_knowledge,
                "used_structured_data": r.used_structured_data, "latency_ms": r.latency_ms,
                "feedback": r.feedback, "llm_provider": r.llm_provider,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]
    }


@router.post("/logs/qa/{log_id}/feedback", dependencies=[Depends(require("logs.view"))])
def qa_feedback(log_id: int, body: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(QaLog, log_id)
    if not row:
        raise HTTPException(404, "问答日志不存在")
    row.feedback = str(body.get("feedback") or "")[:32]
    row.feedback_note = str(body.get("note") or "")[:2000]
    db.commit()
    return {"ok": True}


@router.get("/logs/stats", dependencies=[Depends(require("logs.view"))])
def log_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    total = int(db.query(AgentRunLog).count())
    failed = int(db.query(AgentRunLog).filter(AgentRunLog.status == "failed").count())
    durations = [d for (d,) in db.execute(select(AgentRunLog.duration_ms)).all() if d is not None]
    avg = round(sum(durations) / len(durations), 1) if durations else 0
    qa_total = int(db.query(QaLog).count())
    with_citations = int(db.query(QaLog).filter(QaLog.used_knowledge.is_(True)).count())
    return {
        "runs": total, "failed": failed, "avg_duration_ms": avg,
        "qa_total": qa_total, "qa_with_citations": with_citations,
        "citation_rate": round(with_citations / qa_total * 100, 1) if qa_total else 0,
    }
