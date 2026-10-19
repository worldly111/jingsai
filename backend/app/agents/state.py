"""智能体工作流的状态定义。

LangGraph 的节点在同一个 State 上读写；trace 用 operator.add 累积，
因此每个节点的输入输出与耗时都能完整留痕，供前端展示与测试报告取证。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    profile: dict[str, Any]
    payload: dict[str, Any]
    session_id: int | None
    user_role: str

    # 中间结果
    queries: list[str]
    intent: str
    filters: dict[str, Any]
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    structured: dict[str, Any]
    checks: list[dict[str, Any]]
    plan: dict[str, Any]
    need_retry: bool
    retry_count: int
    gaps: list[str]
    missing_terms: list[str]

    # 输出
    answer: str
    sections: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    charts: list[dict[str, Any]]
    suggestions: list[str]

    # 运行时
    mode: str
    llm_used: bool
    llm_provider: str
    error: str
    trace: Annotated[list[dict[str, Any]], operator.add]


def initial_state(**kwargs: Any) -> AgentState:
    state: AgentState = {
        "question": "",
        "profile": {},
        "payload": {},
        "session_id": None,
        "user_role": "学生",
        "queries": [],
        "intent": "",
        "filters": {},
        "evidence": [],
        "citations": [],
        "structured": {},
        "checks": [],
        "plan": {},
        "need_retry": False,
        "retry_count": 0,
        "gaps": [],
        "missing_terms": [],
        "answer": "",
        "sections": [],
        "tables": [],
        "charts": [],
        "suggestions": [],
        "mode": "offline",
        "llm_used": False,
        "llm_provider": "",
        "error": "",
        "trace": [],
    }
    state.update({k: v for k, v in kwargs.items() if k in state})  # type: ignore[literal-required]
    return state


def trace_entry(node: str, title: str, summary: str, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"node": node, "title": title, "summary": summary}
    entry.update(extra)
    return entry