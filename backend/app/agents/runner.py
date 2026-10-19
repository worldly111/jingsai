"""智能体调度器。

对上层（FastAPI、脚本、测试）只暴露两个入口：
  - `run_agent()`  一次调用返回完整结果（含节点轨迹、表格、图表、引用）；
  - `iter_agent()` 以事件流形式逐节点产出，供前端展示工作流执行过程。

每次运行都会写入 agent_run_logs（节点轨迹与耗时）以及 qa_logs（问答质检日志），
这两张表既是运行审计，也是测试报告与验收取证的直接数据来源。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Iterator

from sqlalchemy.orm import Session

from ..db.models import AgentRunLog, ChatMessage, ChatSession, QaLog
from .graphs import AGENT_LABELS, GRAPH_SPECS, get_graph, graph_overview, validate_graphs
from .state import AgentState, initial_state

# 需要写入 qa_logs 的智能体（知识问答为主，其余为结构化任务）
QA_AGENTS = {"qa", "stats"}


def _config(db: Session, run_id: str) -> dict[str, Any]:
    return {"configurable": {"db": db, "run_id": run_id}}


def _merge_updates(base: dict[str, Any], update: dict[str, Any]) -> None:
    """按 LangGraph 的合并语义累积流式更新（trace 为追加，其余为覆盖）。"""
    for key, value in (update or {}).items():
        if key == "trace":
            base.setdefault("trace", [])
            base["trace"] = base["trace"] + list(value or [])
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            merged = dict(base.get(key) or {})
            merged.update(value)
            base[key] = merged
        else:
            base[key] = value


def _result_payload(agent: str, state: dict[str, Any], run_id: str, duration_ms: int, error: str = "") -> dict[str, Any]:
    structured = state.get("structured") or {}
    return {
        "agent": agent,
        "agent_name": AGENT_LABELS.get(agent, agent),
        "run_id": run_id,
        "mode": state.get("mode") or "offline",
        "llm_used": bool(state.get("llm_used")),
        "llm_provider": state.get("llm_provider") or "",
        "answer": state.get("answer") or "",
        "sections": state.get("sections") or [],
        "tables": state.get("tables") or [],
        "charts": state.get("charts") or [],
        "citations": state.get("citations") or [],
        "checks": state.get("checks") or [],
        "suggestions": state.get("suggestions") or [],
        "structured": structured,
        "steps": state.get("trace") or [],
        "error": error or state.get("error") or "",
        "duration_ms": duration_ms,
    }


def _log_run(
    db: Session,
    agent: str,
    state_input: dict[str, Any],
    payload: dict[str, Any],
    run_id: str,
    duration_ms: int,
) -> None:
    steps = payload.get("steps") or []
    summary = {
        "answer_chars": len(payload.get("answer") or ""),
        "citations": len(payload.get("citations") or []),
        "tables": len(payload.get("tables") or []),
        "charts": len(payload.get("charts") or []),
        "checks": len(payload.get("checks") or []),
        "mode": payload.get("mode"),
    }
    db.add(
        AgentRunLog(
            run_id=run_id,
            agent=agent,
            input_payload={
                "question": state_input.get("question") or "",
                "profile": state_input.get("profile") or {},
                "payload": state_input.get("payload") or {},
            },
            node_trace=steps,
            output_summary=summary,
            status="failed" if payload.get("error") else "success",
            error=str(payload.get("error") or "")[:2000],
            duration_ms=duration_ms,
            llm_provider=payload.get("llm_provider") or "",
        )
    )


def _log_qa(db: Session, state_input: dict[str, Any], payload: dict[str, Any], duration_ms: int) -> None:
    structured = payload.get("structured") or {}
    db.add(
        QaLog(
            session_id=state_input.get("session_id"),
            agent=payload.get("agent") or "qa",
            question=str(state_input.get("question") or "")[:4000],
            answer=payload.get("answer") or "",
            citations=payload.get("citations") or [],
            llm_provider=payload.get("llm_provider") or "",
            used_knowledge=bool(payload.get("citations")),
            used_structured_data=bool(structured.get("stats") or structured.get("competition") or structured.get("overview")),
            latency_ms=duration_ms,
        )
    )


def _prepare(
    agent: str, question: str, profile: dict[str, Any] | None, payload: dict[str, Any] | None,
    session_id: int | None, user_role: str,
) -> AgentState:
    if agent not in GRAPH_SPECS:
        raise KeyError(f"未知智能体：{agent}，可选值：{sorted(GRAPH_SPECS)}")
    return initial_state(
        question=question or "",
        profile=profile or {},
        payload=payload or {},
        session_id=session_id,
        user_role=user_role or "学生",
    )


def run_agent(
    db: Session,
    agent: str,
    *,
    question: str = "",
    profile: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    session_id: int | None = None,
    user_role: str = "学生",
    log: bool = True,
) -> dict[str, Any]:
    """执行一个智能体工作流，返回可直接返回给前端的完整结果。"""
    state = _prepare(agent, question, profile, payload, session_id, user_role)
    run_id = uuid.uuid4().hex[:16]
    started = time.perf_counter()
    error = ""
    try:
        result = dict(get_graph(agent).invoke(state, config=_config(db, run_id)))
    except Exception as exc:  # noqa: BLE001 - 工作流级异常也要落到日志里
        error = str(exc)
        result = dict(state)
        result["error"] = error
    duration_ms = int((time.perf_counter() - started) * 1000)
    out = _result_payload(agent, result, run_id, duration_ms, error)
    if log:
        try:
            _log_run(db, agent, state, out, run_id, duration_ms)
            if agent in QA_AGENTS:
                _log_qa(db, state, out, duration_ms)
            db.commit()
        except Exception:  # noqa: BLE001 - 日志失败不影响业务结果
            db.rollback()
    return out


def iter_agent(
    db: Session,
    agent: str,
    *,
    question: str = "",
    profile: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    session_id: int | None = None,
    user_role: str = "学生",
    log: bool = True,
) -> Iterator[dict[str, Any]]:
    """以事件流方式执行工作流，逐节点产出执行轨迹，最后产出完整结果。

    事件类型：
      - {"type": "step", "node": ..., "title": ..., "summary": ...}
      - {"type": "result", ...完整结果}
    """
    state = _prepare(agent, question, profile, payload, session_id, user_role)
    run_id = uuid.uuid4().hex[:16]
    started = time.perf_counter()
    merged: dict[str, Any] = dict(state)
    error = ""
    yield {"type": "start", "agent": agent, "agent_name": AGENT_LABELS.get(agent, agent), "run_id": run_id}
    try:
        for update in get_graph(agent).stream(state, config=_config(db, run_id), stream_mode="updates"):
            for update_payload in update.values():
                _merge_updates(merged, update_payload or {})
                for entry in (update_payload or {}).get("trace") or []:
                    yield {"type": "step", "run_id": run_id, **entry}
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        merged["error"] = error
    duration_ms = int((time.perf_counter() - started) * 1000)
    out = _result_payload(agent, merged, run_id, duration_ms, error)
    if log:
        try:
            _log_run(db, agent, state, out, run_id, duration_ms)
            if agent in QA_AGENTS:
                _log_qa(db, state, out, duration_ms)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    yield {"type": "result", **out}


# ============================================================
#  会话记录
# ============================================================


def ensure_session(db: Session, session_id: int | None, *, title: str = "", agent: str = "qa",
                   user_ref: str = "", user_role: str = "学生") -> ChatSession:
    if session_id:
        session = db.get(ChatSession, int(session_id))
        if session:
            return session
    session = ChatSession(title=(title or "新会话")[:120], agent=agent, user_ref=user_ref, user_role=user_role)
    db.add(session)
    db.flush()
    return session


def append_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    *,
    citations: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    agent_trace: dict[str, Any] | None = None,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations or [],
        payload=payload or {},
        agent_trace=agent_trace or {},
    )
    db.add(message)
    db.flush()
    return message


# ============================================================
#  元信息
# ============================================================


def agent_catalog() -> list[dict[str, Any]]:
    return graph_overview()


def validate_all() -> list[str]:
    return validate_graphs()


__all__ = [
    "AGENT_LABELS",
    "GRAPH_SPECS",
    "agent_catalog",
    "append_message",
    "ensure_session",
    "get_graph",
    "iter_agent",
    "run_agent",
    "validate_all",
]