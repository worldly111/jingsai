"""LangGraph 工作流编排。

8 个智能体各自是一张 StateGraph；节点 id 与 `backend/prompts/<agent>.yaml` 中声明的
节点一一对应（`validate_graphs()` 在启动时校验），Prompt 与回答规则全部外置。

每个节点都走“双通道”：
  - 配置了大模型时，由模型完成理解与生成；
  - 未配置（或调用失败）时，由 rules/ 规则与结构化台账完成同样的产出。
两条通道输出同一份 AgentState 字段，因此前端与导出模块不需要感知运行模式。
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Budget, Competition, Major
from ..llm import get_llm
from ..rag import RetrievedChunk
from ..services.competition_service import CompetitionService
from ..services.finance_service import FinanceService
from ..services.review_service import ReviewService
from ..services.stats_service import StatsFilter, StatsService
from . import tools as T
from .prompts import answer_rules, build_prompt, node_title, validate_registry
from .state import AgentState, trace_entry

AGENT_LABELS = {
    "qa": "竞赛知识问答",
    "recommend": "竞赛推荐",
    "prep": "备赛辅助",
    "review": "项目指导辅助",
    "budget": "预算申请辅助",
    "loan": "借款辅助",
    "reimbursement": "报销辅助",
    "stats": "竞赛数据统计",
}

# ============================================================
#  公共工具
# ============================================================


def _db(config: RunnableConfig) -> Session:
    return config["configurable"]["db"]


def _mode_fields(state: AgentState, used: bool, provider: str) -> dict[str, Any]:
    any_used = used or bool(state.get("llm_used"))
    prov = (provider or state.get("llm_provider") or "") if any_used else ""
    return {"llm_used": any_used, "llm_provider": prov, "mode": prov or "offline"}


def _evidence_of(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, c in enumerate(chunks, start=1):
        item = c.citation(i)
        item["content"] = c.content
        item["section"] = c.section
        item["page_no"] = c.page_no
        out.append(item)
    return out


def _chunks_from_evidence(evidence: list[dict[str, Any]]) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []
    for e in evidence or []:
        chunks.append(
            RetrievedChunk(
                chunk_id=int(e.get("chunk_id") or 0),
                document_id=int(e.get("document_id") or 0),
                document_title=str(e.get("title") or ""),
                doc_type=str(e.get("doc_type") or ""),
                content=str(e.get("content") or e.get("snippet") or ""),
                score=float(e.get("score") or 0.0),
                section=str(e.get("section") or ""),
                page_no=e.get("page_no"),
                year=e.get("year"),
                doc_no=str(e.get("doc_no") or ""),
                issuing_body=str(e.get("issuing_body") or ""),
                competition_name=str(e.get("competition_name") or ""),
                source_path=str(e.get("source_path") or ""),
                source_url=str(e.get("source_url") or ""),
            )
        )
    return chunks


def _find_competition(db: Session, name: str) -> Competition | None:
    name = (name or "").strip()
    if not name:
        return None
    stmt = select(Competition).where(or_(Competition.name == name, Competition.short_name == name))
    comp = db.execute(stmt).scalars().first()
    if comp:
        return comp
    stmt = select(Competition).where(
        or_(Competition.name.like(f"%{name}%"), Competition.short_name.like(f"%{name}%"))
    )
    return db.execute(stmt).scalars().first()


_CUP_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9·]{2,12}杯")


def _missing_kb_terms(db: Session, question: str, chunks: list[RetrievedChunk]) -> list[str]:
    """识别问题中点名、但知识库原文完全未出现的赛事（如未收录的“挑战杯”）。

    检索器总会返回若干含“报名时间”等泛化词的片段；若不做实体校验，
    这些片段会被误当成证据。此处只拦截以“杯”命名的明确实体，避免误伤普通问题。
    """
    raw_terms = {m.group(0) for m in _CUP_TERM_RE.finditer(question or "")}
    terms: set[str] = set()
    for raw in raw_terms:
        term = re.sub(r"^(?:20\d{2}|第[一二三四五六七八九十百\d]+届|年度|年|届|的|参加|关于|举办|报名)+", "", raw)
        if len(term) >= 2:
            terms.add(term)
    if not terms:
        return []
    corpus = "\n".join(c.content for c in chunks)
    known = " ".join(T.list_competition_names(db))
    return sorted(t for t in terms if t not in corpus and t not in known)


def _profile_text(profile: dict[str, Any]) -> str:
    if not profile:
        return "（未提供画像信息）"
    parts = []
    if profile.get("major"):
        parts.append(f"专业：{profile['major']}")
    if profile.get("grade"):
        parts.append(f"年级：{profile['grade']}")
    if profile.get("tech_tags"):
        parts.append("技术方向：" + "、".join(str(x) for x in profile["tech_tags"]))
    if profile.get("has_project") or profile.get("project_title"):
        parts.append(f"项目基础：{profile.get('project_title') or '有'}")
    if profile.get("preferred_level"):
        parts.append(f"意向级别：{profile['preferred_level']}")
    if profile.get("student_name"):
        parts.append(f"姓名：{profile['student_name']}")
    return "；".join(parts) or "（未提供画像信息）"


def _table(title: str, columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """构造可由前端表格组件与导出模块直接消费的表格结构。"""
    return {
        "kind": "table",
        "title": title,
        "columns": [{"key": k, "label": lb} for k, lb in columns],
        "rows": [{k: r.get(k) for k, _ in columns} for r in rows],
    }


def _md(title: str, content: str) -> dict[str, Any]:
    return {"kind": "markdown", "title": title, "content": content}


def _rows_to_markdown(columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "（无数据）"
    head = "| " + " | ".join(lb for _, lb in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(r.get(k) if r.get(k) is not None else "") for k, _ in columns) + " |"
        for r in rows
    ]
    return "\n".join([head, sep] + body)


def _merge_evidence(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for e in group or []:
            key = int(e.get("chunk_id") or 0)
            if key and key in seen:
                continue
            seen.add(key)
            out.append(e)
    # 重新编号，保证正文中的 [^n] 与参考资料一致
    for i, e in enumerate(out, start=1):
        e["index"] = i
    return out


def _wrap(agent: str, node_id: str, fn: Callable[[AgentState, RunnableConfig], dict[str, Any]]) -> Callable:
    """包装节点：统一补记 trace 与耗时，并把节点异常收敛为可解释的错误状态。"""
    title = node_title(agent, node_id)

    def wrapped(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            out = fn(state, config) or {}
        except Exception as exc:  # noqa: BLE001 - 单节点失败不应中断整条工作流
            elapsed = int((time.perf_counter() - started) * 1000)
            return {
                "error": str(exc),
                "trace": [
                    trace_entry(node_id, title, f"节点执行失败：{exc}", level="error", duration_ms=elapsed)
                ],
            }
        elapsed = int((time.perf_counter() - started) * 1000)
        entries = out.get("trace") or []
        if entries:
            entries[-1].setdefault("duration_ms", elapsed)
        else:
            out["trace"] = [trace_entry(node_id, title, "完成", duration_ms=elapsed)]
        return out

    wrapped.__name__ = f"{agent}__{node_id}"
    return wrapped


def _mk_graph(agent: str, nodes: dict[str, Callable], edges: list[tuple[str, str]],
              branches: list[tuple[str, Callable, dict[str, str]]] | None = None):
    builder = StateGraph(AgentState)
    for node_id, fn in nodes.items():
        builder.add_node(node_id, _wrap(agent, node_id, fn))
    for src, dst in edges:
        builder.add_edge(START if src == "START" else src, END if dst == "END" else dst)
    for src, router, mapping in branches or []:
        builder.add_conditional_edges(src, router, mapping)
    return builder.compile()


# ============================================================
#  一、竞赛知识问答（qa）
# ============================================================


def qa_understand(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    history = str((state.get("payload") or {}).get("history") or "")
    names = "、".join(T.list_competition_names(db)[:40]) or "（台账暂无赛事）"
    system, user = build_prompt(
        "qa", "understand", {"question": question, "history": history or "（无）", "competition_names": names}
    )
    data, mode, used = T.llm_json(
        system, user, fallback=lambda: T.rule_parse_question(db, question, history)
    )
    queries = [str(x).strip() for x in (data.get("queries") or []) if str(x).strip()][:4]
    if not queries:
        queries = [question]
    intent = str(data.get("intent") or "其他")
    competition = str(data.get("competition") or "")
    year = data.get("year")
    out: dict[str, Any] = {
        "queries": queries,
        "intent": intent,
        "filters": {"competition": competition, "year": int(year) if year else None},
        "structured": {"understanding": {"intent": intent, "competition": competition, "year": year,
                                          "need_structured": bool(data.get("need_structured")),
                                          "queries": queries}},
        "trace": [trace_entry("understand", node_title("qa", "understand"),
                              f"识别意图「{intent}」，生成 {len(queries)} 条检索查询")],
    }
    out.update(_mode_fields(state, used, mode))
    return out


def qa_retrieve(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    filters = state.get("filters") or {}
    queries = list(state.get("queries") or [state.get("question", "")])
    if int(state.get("retry_count") or 0) > 0 and state.get("gaps"):
        comp = filters.get("competition") or ""
        queries = queries + [f"{g} {comp}".strip() for g in state["gaps"][:2]]

    # 已识别赛事/年份时限定检索范围，避免把其他赛事的时间节点混入回答
    kb_filters: dict[str, Any] = {}
    comp = _find_competition(db, str(filters.get("competition") or ""))
    if comp:
        kb_filters["competition_id"] = comp.id
    if filters.get("year"):
        kb_filters["year"] = int(filters["year"])

    chunks = T.kb_search(db, queries, top_k=settings.rag_top_k, filters=kb_filters or None)
    scope_note = ""
    if kb_filters:
        scope_note = f"（范围：{comp.name if comp else '全部赛事'}"
        if kb_filters.get("year"):
            scope_note += f" / {kb_filters['year']} 年"
        scope_note += "）"
        if len(chunks) < 2:
            # 范围内的资料可能尚未导入，回退到全库检索并保留范围提示
            chunks = T.kb_search(db, queries, top_k=settings.rag_top_k)
            scope_note = "（限定范围内资料不足，已回退全库检索）"
    missing = _missing_kb_terms(db, state.get("question", ""), chunks)
    if missing:
        return {
            "evidence": [],
            "citations": [],
            "missing_terms": missing,
            "trace": [
                trace_entry("retrieve", node_title("qa", "retrieve"),
                            f"知识库未收录「{'、'.join(missing)}」，已拦截 {len(chunks)} 个无关片段并转人工补充指引")
            ],
        }
    evidence = _evidence_of(chunks)
    return {
        "evidence": evidence,
        "citations": T.build_citations(chunks),
        "trace": [
            trace_entry("retrieve", node_title("qa", "retrieve"),
                        f"混合检索召回 {len(chunks)} 个片段{scope_note}"
                        + (f"，最高相关度 {chunks[0].score:.2f}" if chunks else "（无命中）"))
        ],
    }


def qa_structured_lookup(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    out = dict(state.get("structured") or {})
    tables: list[dict[str, Any]] = []
    question = state.get("question", "")
    comp_name = str((state.get("filters") or {}).get("competition") or "")
    year = (state.get("filters") or {}).get("year")
    svc = CompetitionService(db)

    comp = _find_competition(db, comp_name) if comp_name else None
    if comp:
        detail = svc.detail(comp.id, year)
        ledger = svc.ledger_summary(comp.name)
        out["competition"] = detail or {}
        out["ledger"] = ledger
        if detail:
            rows = [
                {"name": m.get("name"), "date": m.get("start_date") or "", "note": m.get("note", "")}
                for m in detail.get("milestones", [])
            ]
            if rows:
                cols = [("name", "时间节点"), ("date", "日期"), ("note", "说明")]
                tables.append(_table(f"{comp.name} 时间节点", cols, rows))
            awards = detail.get("award_settings") or []
            if awards:
                cols = [("award_level", "奖项"), ("category", "类别"), ("ratio", "获奖比例(%)"),
                        ("quantity", "名额"), ("prize", "奖励"), ("note", "说明")]
                tables.append(_table(f"{comp.name} 奖项设置", cols, awards))

    stats_wanted = state.get("intent") == "数据统计"
    if stats_wanted:
        parsed = T.rule_parse_stats(db, question)
        if comp_name:
            parsed["competitions"] = [comp_name]
        flt = T.to_stats_filter(parsed)
        stats = StatsService(db)
        overview = stats.overview(flt)
        by_year = stats.by_year(flt)
        out["stats"] = {
            "filter": overview.get("filter"),
            "filter_detail": overview.get("filter_detail"),
            "overview": overview,
            "by_year": by_year,
            "by_competition": stats.by_competition(flt),
            "by_award_level": stats.by_award_level(flt),
            "by_major": stats.by_major(flt),
        }
        cols = [("year", "年度"), ("registrations", "参赛队数"), ("awards", "获奖数"),
                ("high_level_awards", "高等级奖"), ("participants", "参赛人次"), ("award_rate", "获奖率%")]
        tables.append(_table("年度参赛与获奖（竞赛台账）", cols, by_year))

    return {
        "structured": out,
        "tables": tables,
        "trace": [
            trace_entry("structured_lookup", node_title("qa", "structured_lookup"),
                        f"台账查询：{'命中赛事 ' + comp.name if comp else '未指定赛事'}"
                        + ("；已附统计结果" if stats_wanted else ""))
        ],
    }


def qa_grade(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    evidence = state.get("evidence") or []
    structured = state.get("structured") or {}
    has_structured = bool(structured.get("competition") or structured.get("stats") or structured.get("ledger"))
    enough = bool(evidence) and (len(evidence) >= 2 or float(evidence[0].get("score") or 0) >= 0.55)
    sufficient = enough or has_structured
    gaps: list[str] = []
    used = False
    mode = "offline"
    if not sufficient:
        system, user = build_prompt(
            "qa", "retrieve",
            {"question": state.get("question", ""),
             "evidence": T.format_evidence(_chunks_from_evidence(evidence))},
        )
        data, mode, used = T.llm_json(
            system, user,
            fallback=lambda: {"sufficient": False, "gaps": [state.get("question", "")]},
        )
        sufficient = bool(data.get("sufficient"))
        gaps = [str(g) for g in (data.get("gaps") or []) if str(g).strip()][:3]

    retry_count = int(state.get("retry_count") or 0)
    need_retry = (not sufficient) and retry_count < 1
    out: dict[str, Any] = {
        "need_retry": need_retry,
        "gaps": gaps or ([state.get("question", "")] if need_retry else []),
        "trace": [
            trace_entry("grade", node_title("qa", "grade"),
                        "证据充分，进入回答生成" if sufficient else
                        ("证据不足，触发一次查询改写重检" if need_retry else "证据仍不足，如实作答"))
        ],
    }
    if need_retry:
        out["retry_count"] = retry_count + 1
    out.update(_mode_fields(state, used, mode))
    return out


def _qa_structured_brief(structured: dict[str, Any]) -> dict[str, Any]:
    brief: dict[str, Any] = {}
    if structured.get("competition"):
        detail = structured["competition"]
        brief["赛事"] = {
            k: detail.get(k) for k in
            ("name", "short_name", "level", "category", "organizer", "official_url", "intro")
            if detail.get(k)
        }
        brief["最新届次"] = {
            k: detail.get(k) for k in
            ("year", "edition_name", "notice_title", "register_start", "register_end",
             "competition_period", "eligibility", "registration_fee", "required_materials")
            if detail.get(k)
        }
        if detail.get("award_settings"):
            brief["奖项设置"] = detail["award_settings"]
        if detail.get("milestones"):
            brief["时间节点"] = detail["milestones"]
    if structured.get("ledger"):
        brief["学院历年数据"] = structured["ledger"]
    if structured.get("stats"):
        brief["统计口径"] = structured["stats"].get("filter")
        brief["统计总览"] = structured["stats"].get("overview")
    return brief


def _stats_trend_text(rows: list[dict[str, Any]]) -> str:
    usable = [r for r in rows if int(r.get("year") or 0) <= date.today().year]
    if len(usable) < 2:
        return ""
    first, last = usable[0], usable[-1]
    peak = max(usable, key=lambda r: int(r.get("awards") or 0))
    return (
        f"获奖数由 {first.get('year')} 年的 {first.get('awards', 0)} 项变为 "
        f"{last.get('year')} 年的 {last.get('awards', 0)} 项，峰值出现在 "
        f"{peak.get('year')} 年（{peak.get('awards', 0)} 项）；同期参赛队数由 "
        f"{first.get('registrations', 0)} 支变为 {last.get('registrations', 0)} 支。"
    )


def _stats_offline_answer(question: str, stats: dict[str, Any]) -> str:
    """把统计口径、关键结论和明细表组织成可直接阅读的回答（数据均来自台账）。"""
    overview = stats.get("overview") or {}
    rows = stats.get("by_year") or []
    label = stats.get("filter") or "全部数据"
    lines = [
        f"**统计口径**：{label}（数据来源：结构化竞赛台账）",
        "",
        "**关键结论**",
        f"- 共 **{overview.get('registrations', 0)}** 支队伍参赛，涉及 "
        f"{overview.get('participants', 0)} 人次、{overview.get('students', 0)} 名学生、"
        f"{overview.get('teachers', 0)} 名指导教师，覆盖 {overview.get('competitions', 0)} 个赛事；",
        f"- 获奖 **{overview.get('awards', 0)}** 项，获奖率 **{overview.get('award_rate', 0)}%**，"
        f"其中特等奖/一等奖 {overview.get('high_level_awards', 0)} 项。",
    ]
    if re.search(r"趋势|变化|历年|近[二两三四五六七八九十\d]+年", question):
        trend = _stats_trend_text(rows)
        if trend:
            lines.append(f"- 年度变化：{trend}")

    by_competition = stats.get("by_competition") or []
    by_award = stats.get("by_award_level") or []
    by_major = stats.get("by_major") or []
    if re.search(r"各赛事|各竞赛|按赛事|赛事分布|各比赛", question) and by_competition:
        title = "按赛事统计"
        cols = [("competition_name", "赛事"), ("registrations", "参赛队数"), ("awards", "获奖数"),
                ("high_level_awards", "高等级奖"), ("award_rate", "获奖率%")]
        table_rows = by_competition
    elif re.search(r"获奖等级|奖项等级|等级分布|获奖分布", question) and by_award:
        title = "按获奖等级统计"
        cols = [("award_grade", "赛事级别"), ("award_level", "获奖等级"), ("count", "数量"), ("ratio", "占比%")]
        table_rows = by_award
    elif "专业" in question and by_major:
        title = "按专业统计"
        cols = [("major", "专业"), ("registrations", "参赛队数"), ("awards", "获奖数"), ("award_rate", "获奖率%")]
        table_rows = by_major
    else:
        title = "年度参赛与获奖"
        cols = [("year", "年度"), ("registrations", "参赛队数"), ("awards", "获奖数"),
                ("high_level_awards", "高等级奖"), ("participants", "参赛人次"), ("award_rate", "获奖率%")]
        table_rows = rows
    lines += ["", f"**{title}**", "", _rows_to_markdown(cols, table_rows)]
    if any(int(r.get("year") or 0) > date.today().year for r in rows):
        lines += ["", "注：未来年度为已登记的计划参赛，获奖数据尚未发生。"]
    return "\n".join(lines)


def qa_synthesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    chunks = _chunks_from_evidence(state.get("evidence") or [])
    structured = state.get("structured") or {}
    citations = state.get("citations") or []
    values = {
        "user_role": state.get("user_role") or "学生",
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("qa")),
        "question": question,
        "profile": _profile_text(state.get("profile") or {}),
        "evidence": T.format_evidence(chunks),
        "structured": T.format_structured(_qa_structured_brief(structured)),
    }
    system, user = build_prompt("qa", "synthesize", values)
    text, ok = T.llm_text(system, user, temperature=0.2)
    used = False
    mode = "offline"
    if ok:
        answer = text
        used = True
        mode = get_llm().provider
    else:
        parts: list[str] = []
        detail = structured.get("competition") or {}
        if detail and detail.get("name") and not structured.get("stats"):
            lines = [
                f"- 赛事级别：{detail.get('level') or '—'}；主办单位：{detail.get('organizer') or '—'}",
            ]
            if detail.get("year"):
                lines.append(
                    f"- 届次：{detail.get('year')} 年 {detail.get('edition_name') or ''}".rstrip()
                )
            if detail.get("register_start") or detail.get("register_end"):
                lines.append(
                    f"- 报名时间：{detail.get('register_start') or '以通知为准'} 至 "
                    f"{detail.get('register_end') or '以通知为准'}"
                )
            if detail.get("competition_period"):
                lines.append(f"- 比赛时间：{detail.get('competition_period')}")
            if detail.get("eligibility"):
                lines.append(f"- 参赛对象与资格：{detail.get('eligibility')}")
            if detail.get("team_size_max"):
                if int(detail.get("team_size_max") or 1) <= 1:
                    lines.append(f"- 组队要求：个人赛；指导教师上限 {detail.get('mentor_limit') or 1} 人")
                else:
                    lines.append(
                        f"- 组队要求：{detail.get('team_size_min') or 1}-{detail.get('team_size_max')} 人，"
                        f"指导教师上限 {detail.get('mentor_limit') or 1} 人"
                    )
            if detail.get("fee_note") or detail.get("registration_fee") is not None:
                lines.append(
                    f"- 报名费：{detail.get('registration_fee') or 0} 元；{detail.get('fee_note') or ''}".strip()
                )
            materials = detail.get("required_materials") or []
            if materials:
                names = "、".join(str(m.get("name") if isinstance(m, dict) else m) for m in materials)
                lines.append(f"- 报名/提交材料：{names}")
            milestones = detail.get("milestones") or []
            if milestones:
                lines.append(
                    "- 关键节点：" + "；".join(
                        f"{m.get('name')} {m.get('start_date') or m.get('end_date') or ''}".strip()
                        for m in milestones[:6]
                    )
                )
            basis = ""
            if detail.get("notice_title"):
                basis = f"\n\n依据：{detail.get('notice_title')}" + (
                    f"（{detail.get('notice_no')}）" if detail.get("notice_no") else ""
                )
            parts.append(T.text_block("赛事信息（来源：结构化赛事台账）", "\n".join(lines) + basis))

        extracted = ""
        if not structured.get("stats"):
            extracted = T.extractive_answer(question, chunks)
        if extracted:
            parts.append(extracted)
        if structured.get("stats"):
            parts.append(_stats_offline_answer(question, structured["stats"]))
        elif structured.get("ledger") and re.search(r"(学院|历年|近[五5]年|获奖|参赛|队次|统计|趋势)", question):
            led = structured["ledger"]
            by_year = led.get("by_year") or []
            detail_lines = [
                f"{y.get('year')} 年：" + "、".join(f"{k} {v} 项" for k, v in y.items() if k != "year")
                for y in by_year
            ]
            parts.append(T.text_block(
                "学院历年参赛与获奖（竞赛台账）",
                f"- 近 5 年参赛 {led.get('registrations', 0)} 队次，获奖 {led.get('awards', 0)} 项"
                + ("\n- " + "\n- ".join(detail_lines) if detail_lines else ""),
            ))
        if not parts:
            parts.append(
                "知识库中没有检索到与该问题直接相关的内容，暂时无法给出有出处的回答。\n\n"
                "建议：请管理员在「知识库管理」中导入对应赛事的最新通知、章程或学院经费管理办法后重试，"
                "或在下方说明希望了解的具体年份与赛项。"
            )
        answer = "\n\n".join(parts)
    refs = T.references_block(citations)
    if refs and structured.get("stats"):
        refs = refs.replace(
            "### 参考资料", "### 相关知识库原文（本回答的统计数字以结构化台账为准）", 1
        )
    answer += refs
    return {
        "answer": answer,
        "sections": [_md("回答", answer)],
        "trace": [trace_entry("synthesize", node_title("qa", "synthesize"),
                              f"生成回答（{len(answer)} 字，引用 {len(citations)} 条）")],
        **_mode_fields(state, used, mode),
    }


def qa_fallback(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    st = T.kb_stats(db)
    question = state.get("question", "")
    intent = state.get("intent") or "其他"
    hints = {
        "时间节点": "该赛事的当年通知（含报名起止与赛程安排）",
        "材料要求": "该赛事的赛题 / 作品提交要求文件",
        "奖项设置": "该赛事的评奖办法或章程",
        "经费制度": "学院《学科竞赛经费管理办法》及差旅费标准",
        "报名条件": "该赛事的参赛章程",
    }
    need = hints.get(intent, "对应赛事的通知、章程与学院相关管理办法")
    missing = state.get("missing_terms") or []
    if missing:
        lead = f"知识库未收录「{'、'.join(missing)}」的通知、章程或相关文件，因此无法给出带出处的回答。"
        need = f"{missing[0]}的当年通知、竞赛章程或学院相关管理办法"
    else:
        lead = f"知识库中没有检索到与「{question}」相关的内容，因此无法给出带出处的回答。"
    answer = (
        f"{lead}\n\n"
        f"当前知识库状态：已收录 {st.get('documents', 0)} 份文件、{st.get('chunks', 0)} 个片段，"
        f"索引类型：{'向量 + 关键词混合' if st.get('has_vector') else '关键词检索'}。\n\n"
        f"建议补充：{need}。导入后在「知识库管理」页面即可立即生效，无需修改代码。\n\n"
        "如该问题涉及参赛或获奖数字，也可以换一种方式提问（例如“2025 年蓝桥杯学院获奖情况”），"
        "我会直接查询结构化台账作答。"
    )
    return {
        "answer": answer,
        "sections": [_md("无法回答的说明", answer)],
        "trace": [trace_entry("fallback", node_title("qa", "fallback"),
                              f"知识库无命中（现有 {st.get('chunks', 0)} 个片段），给出补充资料指引")],
    }


def _qa_route_after_retrieve(state: AgentState) -> str:
    return "structured_lookup" if state.get("evidence") else "fallback"


def _qa_route_after_grade(state: AgentState) -> str:
    return "retrieve" if state.get("need_retry") else "synthesize"


# ============================================================
#  二、竞赛推荐（recommend）
# ============================================================

TECH_TAG_WORDS: dict[str, list[str]] = {
    "算法竞赛": ["算法", "ACM", "程序设计", "编程", "蓝桥"],
    "机器学习": ["机器学习", "深度学习", "人工智能", "AI", "神经网络", "大模型"],
    "数据分析": ["数据分析", "大数据", "数据挖掘", "统计"],
    "前端开发": ["前端", "网页", "Web", "界面"],
    "后端开发": ["后端", "服务端", "接口", "数据库"],
    "嵌入式": ["嵌入式", "单片机", "物联网", "硬件"],
    "电子设计": ["电子设计", "电路", "PCB", "信号"],
    "机器人": ["机器人", "ROS", "自动控制", "无人机"],
    "网络安全": ["网络安全", "信息安全", "CTF", "渗透"],
    "数学建模": ["数学建模", "建模", "数模"],
    "创新创业": ["创新创业", "互联网+", "挑战杯", "创业计划"],
    "视觉设计": ["视觉", "UI", "交互设计", "多媒体"],
}


def _rule_parse_profile(db: Session, question: str, profile: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(profile or {})
    q = question or ""
    if not out.get("major"):
        majors = [m for (m,) in db.execute(select(Major.name)).all() if m]
        out["major"] = next((m for m in sorted(majors, key=len, reverse=True) if m in q), "")
    if not out.get("grade"):
        m = re.search(r"(大[一二三四]|研[一二三])", q)
        if m:
            out["grade"] = m.group(1)
        else:
            m = re.search(r"(20\d{2})\s*级", q)
            if m:
                year = int(m.group(1))
                span = 4 if "研" not in q else 3
                diff = max(1, min(span, 2026 - year + 1)) if year <= 2026 else 1
                out["grade"] = ("研" if "研" in q else "大") + "一二三四"[diff - 1]
    if not out.get("tech_tags"):
        tags = [tag for tag, words in TECH_TAG_WORDS.items() if any(w.lower() in q.lower() for w in words)]
        out["tech_tags"] = tags[:4]
    if "has_project" not in out:
        out["has_project"] = bool(re.search(r"(有(?:个)?项目|已有作品|做过项目|作品基础|参加过大创|有成果)", q))
    if not out.get("project_title"):
        m = re.search(r"项目(?:名称|是|叫)[：: ]*([^\n，。;；]{2,30})", q)
        if m:
            out["project_title"] = m.group(1).strip()
    if not out.get("preferred_level"):
        for lv in ("国家级", "省级", "校级"):
            if lv in q:
                out["preferred_level"] = lv
                break
    return out


def _recommend_parse_profile(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    profile = state.get("profile") or {}
    system, user = build_prompt(
        "recommend", "parse_profile",
        {"question": question, "profile": _profile_text(profile)},
    )
    data, mode, used = T.llm_json(
        system, user, fallback=lambda: _rule_parse_profile(db, question, profile)
    )
    merged = {**(_rule_parse_profile(db, question, profile)), **{k: v for k, v in data.items() if v not in (None, "", [], False)}}
    if not merged.get("tech_tags") and profile.get("tech_tags"):
        merged["tech_tags"] = profile["tech_tags"]
    summary = _profile_text(merged)
    out: dict[str, Any] = {
        "profile": merged,
        "structured": {"profile": merged},
        "trace": [trace_entry("parse_profile", node_title("recommend", "parse_profile"), f"画像：{summary}")],
    }
    out.update(_mode_fields(state, used, mode))
    return out


def _recommend_score(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    profile = state.get("profile") or {}
    result = CompetitionService(db).recommend(profile, top_n=6)
    recos = result.get("recommendations") or []
    cols = [("name", "赛事"), ("level", "级别"), ("difficulty", "难度"), ("score", "适配度"),
            ("register_end", "报名截止"), ("registration_fee", "报名费")]
    rows = [
        {**r, "registration_fee": (f"{r['registration_fee']:.0f} 元" if r.get("registration_fee") else "—")}
        for r in recos
    ]
    return {
        "structured": {**(state.get("structured") or {}), "recommend": result},
        "tables": [_table("推荐清单（按适配度排序）", cols, rows)] if recos else [],
        "trace": [trace_entry("score", node_title("recommend", "score"),
                              f"对 {result.get('total_candidates', 0)} 个在库赛事打分，输出前 {len(recos)} 个推荐")],
    }


def _recommend_enrich(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    recos = ((state.get("structured") or {}).get("recommend") or {}).get("recommendations") or []
    queries: list[str] = []
    for r in recos[:3]:
        name = r.get("name") or ""
        queries += [f"{name} 报名 材料要求", f"{name} 赛程 时间节点"]
    chunks = T.kb_search(db, queries, top_k=4)
    evidence = _evidence_of(chunks)
    return {
        "evidence": evidence,
        "citations": T.build_citations(chunks),
        "trace": [trace_entry("enrich_kb", node_title("recommend", "enrich_kb"),
                              f"为候选赛事补充 {len(chunks)} 个规程片段")],
    }


def _recommend_answer(result: dict[str, Any]) -> str:
    recos = result.get("recommendations") or []
    if not recos:
        return "台账中没有可推荐的赛事。请先在「赛事台账」中补充赛事数据后重试。"
    cols = [("name", "赛事名称"), ("level", "级别"), ("difficulty", "难度"), ("score", "适配度"),
            ("register_end", "报名截止"), ("registration_fee", "报名费")]
    rows = [
        {**r, "registration_fee": (f"{r['registration_fee']:.0f} 元" if r.get("registration_fee") else "—"),
         "register_end": r.get("register_end") or "以当年通知为准"}
        for r in recos
    ]
    parts = [f"为你从 {result.get('total_candidates', 0)} 个在库赛事中匹配出 {len(recos)} 个适合参加的竞赛：", "",
             _rows_to_markdown(cols, rows), "", "**推荐理由（前三项）**"]
    for r in recos[:3]:
        ledger = r.get("college_ledger") or {}
        parts.append(
            f"- **{r['name']}**（适配度 {r['score']}）：{('；'.join(r.get('reasons') or []) or '综合条件匹配')}。"
            f"学院历年参赛 {ledger.get('registrations', 0)} 队次、获奖 {ledger.get('awards', 0)} 项（来源：竞赛台账）。"
        )
    best = recos[0]
    parts += ["", f"**如果只能选一个**：建议先参加 **{best['name']}**，"
                  f"原因是{('；'.join(best.get('reasons') or []) or '与你的条件匹配度最高')}。", "",
              "**下一步动作**", "1. 核对报名截止时间，确认组队与指导教师；",
              "2. 到「备赛辅助」生成本赛事的备赛计划与材料清单；",
              "3. 如需参赛经费，到「预算申请」按人数与行程编制预算。"]
    return "\n".join(parts)


def _recommend_synthesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    structured = state.get("structured") or {}
    result = structured.get("recommend") or {}
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("recommend")),
        "profile": _profile_text(state.get("profile") or {}),
        "structured": T.format_structured(result),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("recommend", "synthesize", values)
    text, ok = T.llm_text(system, user, temperature=0.3)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _recommend_answer(result) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("推荐结果", answer)],
        "trace": [trace_entry("synthesize", node_title("recommend", "synthesize"), f"生成推荐说明（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  三、备赛辅助（prep）
# ============================================================


def _prep_resolve_event(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    payload = dict(state.get("payload") or {})
    question = state.get("question", "")
    if not payload.get("competition_name") and not payload.get("competition_id"):
        for name in sorted(T.list_competition_names(db), key=len, reverse=True):
            if name and name in question:
                payload["competition_name"] = name
                break
    name = payload.get("competition_name") or payload.get("competition_id") or ""
    comp = None
    if payload.get("competition_id"):
        comp = db.get(Competition, int(payload["competition_id"]))
    if not comp and name:
        comp = _find_competition(db, str(name))
    if not comp:
        available = CompetitionService(db).list_competitions()[:10]
        out: dict[str, Any] = {
            "structured": {"event": {}, "plan_error": "未识别到赛事，请先在下方选择要备赛的赛事。"},
            "sections": [],
            "tables": [_table("可选赛事（台账）", [("name", "赛事"), ("level", "级别"), ("latest_year", "最近年度")],
                              [{"name": c.get("name"), "level": c.get("level"), "latest_year": c.get("latest_year")}
                               for c in available])],
            "trace": [trace_entry("resolve_event", node_title("prep", "resolve_event"),
                                  "未识别到赛事，返回台账赛事供选择")],
        }
        return out
    payload["competition_name"] = comp.name
    svc = CompetitionService(db)
    detail = svc.detail(comp.id, payload.get("year"))
    ledger = svc.ledger_summary(comp.name)
    return {
        "payload": payload,
        "structured": {"event": detail or {}, "ledger": ledger},
        "trace": [trace_entry("resolve_event", node_title("prep", "resolve_event"),
                              f"定位赛事：{comp.name}（{comp.level}）")],
    }


def _prep_build_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    structured = dict(state.get("structured") or {})
    if structured.get("plan_error"):
        return {"structured": structured}
    payload = dict(state.get("payload") or {})
    try:
        plan = CompetitionService(db).prep_plan(payload)
    except ValueError as exc:
        structured["plan_error"] = str(exc)
        return {"structured": structured,
                "trace": [trace_entry("build_plan", node_title("prep", "build_plan"), f"无法生成计划：{exc}", level="warning")]}
    rows = [
        {"stage": s.get("stage"), "start": s.get("start"), "end": s.get("end"),
         "tasks": "；".join(s.get("tasks") or [])[:160], "deliverable": (s.get("tasks") or [""])[-1]}
        for s in plan.get("timeline") or []
    ]
    cols = [("stage", "阶段"), ("start", "开始"), ("end", "结束"), ("tasks", "关键任务"), ("deliverable", "交付物")]
    structured["plan"] = plan
    return {
        "structured": structured,
        "tables": [_table("备赛阶段计划（倒排）", cols, rows)] if rows else [],
        "trace": [trace_entry("build_plan", node_title("prep", "build_plan"),
                              f"倒排 {len(rows)} 个阶段，距目标日期 {plan.get('days_left')} 天")],
    }


def _prep_retrieve(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    plan = (state.get("structured") or {}).get("plan") or {}
    name = ((plan.get("competition") or {}).get("name")) or (state.get("payload") or {}).get("competition_name") or ""
    if not name:
        return {"trace": [trace_entry("retrieve_materials", node_title("prep", "retrieve_materials"), "无赛事，跳过规程检索")]}
    queries = [f"{name} 材料 提交 要求", f"{name} 报名 组队 规则"]
    material_names = [m.get("name") for m in (plan.get("materials") or []) if m.get("name")]
    if material_names:
        queries.append(f"{name} {' '.join(material_names[:3])} 格式 要求")
    chunks = T.kb_search(db, queries, top_k=5)
    evidence = _evidence_of(chunks)
    return {
        "evidence": evidence,
        "citations": T.build_citations(chunks),
        "trace": [trace_entry("retrieve_materials", node_title("prep", "retrieve_materials"),
                              f"检索到 {len(chunks)} 个规程片段")],
    }


def _prep_answer(plan: dict[str, Any], structured: dict[str, Any]) -> str:
    if structured.get("plan_error"):
        return structured["plan_error"] + "\n\n请先在「赛事台账」选择赛事，或直接输入赛事名称（如：中国国际大学生创新大赛）。"
    comp = plan.get("competition") or {}
    ed = plan.get("edition") or {}
    if plan.get("expired"):
        parts = [
            f"**{comp.get('name', '')}**：所查询届次（{ed.get('year') or '—'}）的报名截止日期为 "
            f"{plan.get('target_date')}，已过去 **{abs(plan.get('days_left', 0))} 天**，不再按该届节点倒排计划。",
            "",
            "以下整理该届的报名窗口、材料与组队要求，可作为下一届备赛参考；"
            "下一届通知发布后，可在赛事台账更新届次信息，再重新生成计划。",
            "",
            f"报名窗口：{ed.get('register_start') or '以当年通知为准'} 至 {ed.get('register_end') or '以当年通知为准'}；"
            f"比赛周期：{ed.get('competition_period') or '以当年通知为准'}。",
            "",
            "**材料与备赛要点**",
        ]
    else:
        parts = [
            f"**{comp.get('name', '')}** 备赛计划：距离目标日期（{plan.get('target_date')}）还有 "
            f"**{plan.get('days_left', 0)} 天**，共 {plan.get('checklist_total', 0)} 项任务与材料。",
            "",
            f"报名窗口：{ed.get('register_start') or '以当年通知为准'} 至 {ed.get('register_end') or '以当年通知为准'}；"
            f"比赛周期：{ed.get('competition_period') or '以当年通知为准'}。",
            "",
            "**阶段计划（倒排）**",
        ]
        cols = [("stage", "阶段"), ("start", "开始"), ("end", "结束"), ("tasks", "关键任务")]
        parts.append(_rows_to_markdown(cols, plan.get("timeline") or []))
    parts += ["", "**材料准备清单**"]
    for m in plan.get("materials") or []:
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        reqs = "、".join(str(r) for r in (m.get("requirements") or []) if str(r).strip()) or "按规程要求"
        desc = str(m.get("description") or "").strip()
        detail = "；".join(x for x in (desc, f"要求：{reqs}") if x)
        parts.append(f"- **{name}**：{detail}")
        advice = str(m.get("advice") or "").strip()
        if advice and advice != reqs:
            parts.append(f"  - 提醒：{advice}")
    notes = plan.get("notes") or []
    if notes:
        parts += ["", "**容易被忽略的提醒**"] + [f"- {n}" for n in notes]
    return "\n".join(parts)


def _prep_synthesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    structured = state.get("structured") or {}
    plan = structured.get("plan") or {}
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("prep")),
        "profile": _profile_text(state.get("profile") or {}),
        "structured": T.format_structured(plan),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("prep", "synthesize", values)
    text, ok = T.llm_text(system, user, temperature=0.3)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _prep_answer(plan, structured) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("备赛方案", answer)],
        "trace": [trace_entry("synthesize", node_title("prep", "synthesize"), f"生成备赛方案（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  四、项目指导辅助（review）
# ============================================================


def _review_prepare(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    payload = dict(state.get("payload") or {})
    text = str(payload.get("text") or state.get("question") or "")
    svc = ReviewService()
    material_type = str(payload.get("material_type") or "")
    if not material_type or material_type not in svc.materials:
        material_type = svc.detect_type(text)
    label = str((svc.materials.get(material_type) or {}).get("label") or "项目材料")
    return {
        "payload": {**payload, "text": text, "material_type": material_type},
        "structured": {"material_type": material_type, "material_label": label, "word_count": len(text)},
        "trace": [trace_entry("prepare_text", node_title("review", "prepare_text"),
                              f"材料类型：{label}，共 {len(text)} 字")],
    }


def _review_rule_check(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    payload = state.get("payload") or {}
    structured = dict(state.get("structured") or {})
    text = str(payload.get("text") or "")
    if not text.strip():
        structured["review_error"] = "未收到材料正文，请粘贴文本或上传 PDF/Word 文件后重试。"
        return {"structured": structured,
                "trace": [trace_entry("rule_check", node_title("review", "rule_check"), "材料为空", level="warning")]}
    result = ReviewService().check(
        text,
        str(payload.get("material_type") or ""),
        competition_name=str(payload.get("competition_name") or ""),
    )
    data = result.to_dict()
    structured["review"] = data
    checks = [
        {"code": i.get("code", ""), "level": i.get("level", "info"), "message": i.get("message", ""),
         "suggestion": i.get("suggestion", "")}
        for i in data.get("issues") or []
    ]
    rows = [
        {"name": s.get("name"), "found": "已包含" if s.get("found") else "缺失",
         "length": s.get("length"), "min_length": s.get("min_length"),
         "advice": s.get("advice")}
        for s in data.get("sections") or []
    ]
    cols = [("name", "必备章节"), ("found", "状态"), ("length", "现有字数"), ("min_length", "建议字数"), ("advice", "要求")]
    return {
        "structured": structured,
        "checks": checks,
        "tables": [_table("章节完整性核对表", cols, rows)],
        "trace": [trace_entry("rule_check", node_title("review", "rule_check"),
                              f"量表检查完成：评分 {data.get('score')}，发现 {len(checks)} 个问题")],
    }


def _review_llm_suggest(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    structured = dict(state.get("structured") or {})
    review = structured.get("review") or {}
    if not review:
        return {"structured": structured}
    payload = state.get("payload") or {}
    text = str(payload.get("text") or "")
    values = {
        "material_label": structured.get("material_label") or "项目材料",
        "checks": T.summarize_checks(state.get("checks") or []),
        "excerpt": text[:2000],
        "suggestions": "\n".join(f"- {s}" for s in review.get("highlights") or []) or "（无）",
    }
    system, user = build_prompt("review", "llm_suggest", values)
    data, mode, used = T.llm_json(system, user, fallback=lambda: {})
    extra_suggestions = [str(x) for x in (data.get("suggestions") or []) if str(x).strip()]
    extra_questions = [str(x) for x in (data.get("questions") or []) if str(x).strip()]
    rewrites = data.get("rewrites") or []
    if extra_suggestions or extra_questions:
        structured["llm_extra"] = {"suggestions": extra_suggestions, "questions": extra_questions, "rewrites": rewrites}
    return {
        "structured": structured,
        "suggestions": extra_suggestions,
        "trace": [trace_entry("llm_suggest", node_title("review", "llm_suggest"),
                              f"生成 {len(extra_suggestions)} 条改写建议、{len(extra_questions)} 个追问"
                              if (extra_suggestions or extra_questions) else "未启用大模型，使用量表内置建议")],
        **_mode_fields(state, used, mode),
    }


def _review_answer(structured: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    if structured.get("review_error"):
        return structured["review_error"]
    review = structured.get("review") or {}
    extra = structured.get("llm_extra") or {}
    parts = [
        f"**整体评价**：材料类型为「{review.get('material_label')}」，共 {review.get('word_count', 0)} 字，"
        f"初检评分 **{review.get('score')} / 100**（评分依据：章节完整性、篇幅、要素覆盖、规范性，量表见 data/rules/review_rubrics.yaml）。",
        "",
    ]
    order = {"error": "必须修改", "warning": "建议修改", "info": "可选优化", "pass": "已通过"}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for c in checks:
        grouped.setdefault(order.get(str(c.get("level")), "可选优化"), []).append(c)
    for bucket in ("必须修改", "建议修改", "可选优化", "已通过"):
        items = grouped.get(bucket) or []
        if not items:
            continue
        parts.append(f"**{bucket}**")
        for c in items:
            line = f"- {c.get('message')}"
            if c.get("suggestion"):
                line += f"　→ {c['suggestion']}"
            parts.append(line)
        parts.append("")
    if review.get("highlights"):
        parts.append("**材料亮点**")
        parts += [f"- {h}" for h in review["highlights"]]
        parts.append("")
    questions = list(review.get("questions") or []) + list(extra.get("questions") or [])
    if questions:
        parts.append("**预答辩问题（按被问到的可能性排序）**")
        parts += [f"{i}. {q}" for i, q in enumerate(questions[:8], start=1)]
        parts.append("")
    if extra.get("suggestions"):
        parts.append("**具体改写建议**")
        parts += [f"- {s}" for s in extra["suggestions"]]
        parts.append("")
    if extra.get("rewrites"):
        parts.append("**可直接套用的改写示例**")
        for r in extra["rewrites"][:5]:
            parts.append(f"- 「{r.get('section', '')}」：{r.get('example', '')}")
    return "\n".join(parts).strip()


def _review_compose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    structured = state.get("structured") or {}
    checks = state.get("checks") or []
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("review")),
        "question": state.get("question", ""),
        "material_label": structured.get("material_label") or "项目材料",
        "structured": T.format_structured(structured.get("review") or {}),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("review", "compose", values)
    text, ok = T.llm_text(system, user, temperature=0.25)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _review_answer(structured, checks) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("材料检查报告", answer)],
        "suggestions": list((structured.get("review") or {}).get("questions") or [])[:8],
        "trace": [trace_entry("compose", node_title("review", "compose"), f"生成检查报告（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  五、预算申请辅助（budget）
# ============================================================


def _event_info(db: Session, name: str) -> dict[str, Any]:
    comp = _find_competition(db, name) if name else None
    if not comp:
        return {}
    edition = CompetitionService(db).latest_edition(comp.id)
    if not edition:
        return {"competition_name": comp.name, "level": comp.level}
    fee_note = edition.fee_note or ""
    fee_unit = "元/人"
    for token in ("元/队", "元/件", "元/项", "元/人"):
        if token in fee_note:
            fee_unit = token
            break
    return {
        "competition_name": comp.name,
        "level": comp.level,
        "year": edition.year,
        "registration_fee": float(edition.registration_fee or 0),
        "registration_fee_unit": fee_unit,
        "competition_period": edition.competition_period or "",
    }


def _budget_parse(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    payload = dict(state.get("payload") or {})
    event = _event_info(db, str(payload.get("competition_name") or ""))
    system, user = build_prompt(
        "budget", "parse_params",
        {"question": question, "payload": T.format_structured(payload, 1200),
         "event_info": T.format_structured(event, 800)},
    )
    data, mode, used = T.llm_json(
        system, user, fallback=lambda: T.rule_parse_budget(db, question, payload, event)
    )
    merged = dict(payload)
    for k, v in data.items():
        if v not in (None, "", [], 0) or k not in merged:
            merged[k] = v
    # 数值字段以规则结果兜底：payload 显式值 > 模型抽取 > 规则抽取
    rule_out = T.rule_parse_budget(db, question, payload, event)
    for k in ("competition_name", "competition_level", "student_count", "teacher_count", "destination",
              "trip_days", "transport_mode", "registration_fee", "registration_fee_unit", "team_name", "year"):
        if merged.get(k) in (None, "", 0) and rule_out.get(k) not in (None, "", 0):
            merged[k] = rule_out[k]
    if not merged.get("competition_level") and merged.get("competition_name"):
        comp = _find_competition(db, str(merged["competition_name"]))
        if comp:
            merged["competition_level"] = comp.level
    return {
        "payload": merged,
        "structured": {"params": merged, "event": event},
        "trace": [trace_entry("parse_params", node_title("budget", "parse_params"),
                              f"预算要素：{merged.get('competition_name') or '未填赛事'}、"
                              f"{merged.get('student_count') or 0} 名学生、{merged.get('trip_days') or 0} 天")],
        **_mode_fields(state, used, mode),
    }


def _budget_compute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    payload = state.get("payload") or {}
    plan = FinanceService(db).plan_budget(payload)
    data = plan.to_dict()
    rows = data.get("items") or []
    cols = [("category", "费用类别"), ("item_name", "项目"), ("unit_price", "单价"), ("quantity", "数量"),
            ("amount", "金额"), ("calc_basis", "计算依据")]
    return {
        "structured": {**(state.get("structured") or {}), "budget": data},
        "checks": data.get("checks") or [],
        "tables": [_table("预算明细（按费用标准测算）", cols, rows)],
        "trace": [trace_entry("compute", node_title("budget", "compute"),
                              f"测算 {len(rows)} 行明细，合计 {data.get('total')} 元（{data.get('total_upper')}）")],
    }


def _budget_policy_lookup(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    queries = ["学科竞赛经费管理办法 开支范围 审批", "差旅费 住宿费 伙食补助 标准", "经费报销 票据 要求"]
    chunks = T.kb_search(db, queries, top_k=4)
    evidence = _evidence_of(chunks)
    return {
        "evidence": evidence,
        "citations": T.build_citations(chunks),
        "trace": [trace_entry("policy_lookup", node_title("budget", "policy_lookup"),
                              f"检索经费制度原文 {len(chunks)} 个片段")],
    }


def _budget_answer(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    cols = [("category", "费用类别"), ("item_name", "项目"), ("unit_price", "单价"), ("quantity", "数量"),
            ("amount", "金额"), ("calc_basis", "计算依据")]
    approval = data.get("approval") or {}
    parts = [
        f"**预算合计 {data.get('total')} 元（大写：{data.get('total_upper')}）**",
        "",
        _rows_to_markdown(cols, items),
        "",
        f"**审批流程**：{approval.get('route') or approval.get('label') or '按学院经费管理办法执行'}"
        + (f"（{approval.get('note')}）" if approval.get("note") else ""),
    ]
    checks = data.get("checks") or []
    if checks:
        parts += ["", "**风险提示**", T.summarize_checks(checks)]
    if data.get("standards_used"):
        parts += ["", "**依据的费用标准**：" + "、".join(data["standards_used"])]
    if data.get("generated_text"):
        parts += ["", "---", "", "**预算申请正文（可直接提交）**", "", data["generated_text"]]
    return "\n".join(parts)


def _budget_compose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    data = ((state.get("structured") or {}).get("budget")) or {}
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("budget")),
        "payload": T.format_structured(state.get("payload") or {}, 1200),
        "structured": T.format_structured(data, 3600),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("budget", "compose", values)
    text, ok = T.llm_text(system, user, temperature=0.2)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _budget_answer(data) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("预算申请", answer)],
        "trace": [trace_entry("compose", node_title("budget", "compose"), f"生成预算申请（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  六、借款辅助（loan）
# ============================================================


def _loan_load_budget(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    payload = dict(state.get("payload") or {})
    rule_out = T.rule_parse_loan(db, question, payload)
    merged = {**rule_out, **{k: v for k, v in payload.items() if v not in (None, "")}}
    # 自然语言里的“借款人：张三”解析结果为 borrower_name，服务层读 borrower.name
    if merged.get("borrower_name") and not merged.get("borrower"):
        merged["borrower"] = {"name": merged["borrower_name"]}
    budget = None
    if merged.get("budget_id"):
        budget = db.get(Budget, int(merged["budget_id"]))
    elif merged.get("budget_doc_no"):
        budget = db.execute(
            select(Budget).where(Budget.doc_no == str(merged["budget_doc_no"]))
        ).scalars().first()
    structured: dict[str, Any] = {**(state.get("structured") or {}), "loan_params": merged, "budget": None}
    if budget:
        merged["budget_id"] = budget.id
        structured["budget"] = {
            "id": budget.id, "doc_no": budget.doc_no, "title": budget.title,
            "competition_name": budget.competition_name, "total_amount": float(budget.total_amount or 0),
            "approved_amount": float(budget.approved_amount or 0), "status": budget.status,
        }
    return {
        "payload": merged,
        "structured": structured,
        "trace": [trace_entry("load_budget", node_title("loan", "load_budget"),
                              f"关联预算单：{budget.doc_no}（{budget.status}）" if budget else "未关联到预算单")],
    }


def _loan_compute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    payload = state.get("payload") or {}
    result = FinanceService(db).plan_loan(payload)
    return {
        "structured": {**(state.get("structured") or {}), "loan": result},
        "checks": result.get("checks") or [],
        "trace": [trace_entry("compute", node_title("loan", "compute"),
                              f"借款金额 {result.get('amount')} 元，{len(result.get('checks') or [])} 项校验")],
    }


def _loan_answer(result: dict[str, Any]) -> str:
    content = result.get("content") or {}
    rows = [{"field": k, "value": v} for k, v in content.items() if v not in (None, "", [], {})]
    cols = [("field", "借款单字段"), ("value", "填写内容")]
    parts = [
        f"**借款金额 {result.get('amount')} 元（大写：{result.get('amount_upper')}）**",
        "",
        _rows_to_markdown(cols, rows),
        "",
        "**校验结论**",
        T.summarize_checks(result.get("checks") or []),
        "",
        "**后续步骤**",
        "1. 借款人签字后送学院负责人审批；",
        "2. 到财务处办理暂付款，领取款项；",
        "3. 赛后 30 日内取得票据并办理冲销（报销），前账未清不得再借。",
    ]
    if result.get("generated_text"):
        parts += ["", "---", "", "**借款单内容（可直接打印填写）**", "", result["generated_text"]]
    return "\n".join(parts)


def _loan_compose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    result = ((state.get("structured") or {}).get("loan")) or {}
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("loan")),
        "structured": T.format_structured(result, 3600),
        "checks": T.summarize_checks(state.get("checks") or []),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("loan", "compose", values)
    text, ok = T.llm_text(system, user, temperature=0.2)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _loan_answer(result) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("借款单", answer)],
        "trace": [trace_entry("compose", node_title("loan", "compose"), f"生成借款单（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  七、报销辅助（reimbursement）
# ============================================================


def _reimb_parse_items(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    payload = dict(state.get("payload") or {})
    rule_out = T.rule_parse_expenses(db, question, payload)
    system, user = build_prompt(
        "reimbursement", "parse_items",
        {"question": question, "payload": T.format_structured(payload, 1500)},
    )
    data, mode, used = T.llm_json(system, user, fallback=lambda: rule_out)
    merged = dict(payload)
    for k, v in data.items():
        if v not in (None, "", [], {}):
            merged[k] = v
    for k in ("items", "claimant_name", "competition_name", "event_end_date", "budget_doc_no", "loan_doc_no"):
        if not merged.get(k) and rule_out.get(k):
            merged[k] = rule_out[k]
    items = [i for i in (merged.get("items") or []) if isinstance(i, dict)]
    total = sum(float(i.get("amount") or 0) for i in items)
    return {
        "payload": merged,
        "structured": {"params": merged, "item_count": len(items), "amount": round(total, 2)},
        "trace": [trace_entry("parse_items", node_title("reimbursement", "parse_items"),
                              f"解析 {len(items)} 笔支出，合计 {round(total, 2)} 元")],
        **_mode_fields(state, used, mode),
    }


def _reimb_compute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    payload = state.get("payload") or {}
    if not (payload.get("items") or []):
        return {
            "structured": {**(state.get("structured") or {}), "reimb_error": "未解析到任何支出明细，请粘贴支出清单或填写表格。"},
            "trace": [trace_entry("compute", node_title("reimbursement", "compute"), "无支出明细", level="warning")],
        }
    result = FinanceService(db).plan_reimbursement(payload)
    data = dict(result)
    rows = data.get("items") or []
    cols = [("category", "费用类别"), ("item_name", "项目"), ("amount", "金额"), ("expense_date", "发生日期"),
            ("invoice_no", "发票号"), ("has_invoice", "有票"), ("over_standard", "超标准")]
    rows = [
        {**r, "has_invoice": "是" if r.get("has_invoice") else "否", "over_standard": "是" if r.get("over_standard") else ""}
        for r in rows
    ]
    return {
        "structured": {**(state.get("structured") or {}), "reimbursement": data},
        "checks": data.get("checks") or [],
        "tables": [_table("支出明细与票据核对", cols, rows)],
        "trace": [trace_entry("compute", node_title("reimbursement", "compute"),
                              f"报销合计 {data.get('total')} 元，完整性评分 {data.get('completeness_score')}")],
    }


def _reimb_answer(data: dict[str, Any], structured: dict[str, Any]) -> str:
    if structured.get("reimb_error"):
        return structured["reimb_error"]
    rows = data.get("items") or []
    cols = [("category", "费用类别"), ("item_name", "项目"), ("amount", "金额"),
            ("expense_date", "发生日期"), ("invoice_no", "发票号"), ("calc_basis", "依据")]
    parts = [
        f"**报销合计 {data.get('total')} 元（大写：{data.get('total_upper')}）**，"
        f"材料完整性评分 **{data.get('completeness_score')} / 100**。",
        "",
        _rows_to_markdown(cols, rows),
    ]
    checks = data.get("checks") or []
    errors = [c for c in checks if c.get("level") == "error"]
    warns = [c for c in checks if c.get("level") == "warning"]
    infos = [c for c in checks if c.get("level") == "info"]
    if errors:
        parts += ["", "**不可报销 / 必须处理项**", T.summarize_checks(errors)]
    if warns:
        parts += ["", "**需说明或修正项**", T.summarize_checks(warns)]
    if infos:
        parts += ["", "**提示项**", T.summarize_checks(infos)]
    missing = [c for c in checks if c.get("suggestion") and c.get("level") in {"error", "warning"}]
    if missing:
        parts += ["", "**待补材料 / 待办清单**"]
        parts += [f"- {c.get('message')}　→ {c.get('suggestion')}" for c in missing]
    if data.get("budget"):
        b = data["budget"]
        parts += ["", f"**预算比对**：关联预算单 {b.get('doc_no')}（批准 {b.get('approved_amount')} 元）"]
    if data.get("loan"):
        l = data["loan"]
        parts += ["", f"**借款冲销**：关联借款单 {l.get('doc_no')}（{l.get('amount')} 元），"
                      f"冲销后{'应退' if (l.get('amount') or 0) > (data.get('total') or 0) else '应补'}"
                      f" {abs(round((l.get('amount') or 0) - (data.get('total') or 0), 2))} 元。"]
    if data.get("generated_text"):
        parts += ["", "---", "", "**报销单内容（可直接打印填写）**", "", data["generated_text"]]
    return "\n".join(parts)


def _reimb_compose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    data = ((state.get("structured") or {}).get("reimbursement")) or {}
    structured = state.get("structured") or {}
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("reimbursement")),
        "structured": T.format_structured(data, 3600),
        "checks": T.summarize_checks(state.get("checks") or []),
        "evidence": T.format_evidence(_chunks_from_evidence(state.get("evidence") or [])),
    }
    system, user = build_prompt("reimbursement", "compose", values)
    text, ok = T.llm_text(system, user, temperature=0.2)
    used = False
    mode = "offline"
    if ok:
        answer = text + T.references_block(state.get("citations") or [])
        used, mode = True, get_llm().provider
    else:
        answer = _reimb_answer(data, structured) + T.references_block(state.get("citations") or [])
    return {
        "answer": answer,
        "sections": [_md("报销单", answer)],
        "trace": [trace_entry("compose", node_title("reimbursement", "compose"), f"生成报销单（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  八、竞赛数据统计（stats）
# ============================================================

_STATS_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "year": [("year", "年度"), ("registrations", "参赛队数"), ("awards", "获奖数"),
             ("high_level_awards", "高等级奖"), ("participants", "参赛人次"), ("award_rate", "获奖率%")],
    "competition": [("competition_name", "赛事"), ("registrations", "参赛队数"), ("awards", "获奖数"),
                    ("high_level_awards", "高等级奖"), ("award_rate", "获奖率%")],
    "major": [("major", "专业"), ("registrations", "参赛队数"), ("awards", "获奖数"), ("award_rate", "获奖率%")],
    "award_level": [("award_level", "获奖等级"), ("award_grade", "奖项"), ("count", "数量"), ("ratio", "占比%")],
    "level": [("level", "赛事级别"), ("registrations", "参赛队数"), ("awards", "获奖数")],
    "teacher": [("teacher", "指导教师"), ("registrations", "指导队数"), ("awards", "获奖数"),
                ("high_level_awards", "高等级奖"), ("student_count", "涉及学生"), ("competition_count", "涉及赛事")],
    "student": [("student", "学生"), ("registrations", "参赛数"), ("awards", "获奖数"),
                ("majors", "专业"), ("points", "积分")],
    "workload": [("teacher", "指导教师"), ("workload", "工作量(学时)"), ("awards", "获奖数"),
                 ("student_points", "学生积分")],
}

_STATS_DIM_LABEL = {
    "year": "年度", "competition": "赛事", "major": "专业", "teacher": "指导教师",
    "student": "学生", "award_level": "获奖等级", "level": "赛事级别", "workload": "教师工作量",
}


def _stats_parse(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    question = state.get("question", "")
    comp_names = "、".join(T.list_competition_names(db)[:40]) or "（暂无）"
    major_names = "、".join(m for (m,) in db.execute(select(Major.name)).all() if m) or "（暂无）"
    system, user = build_prompt(
        "stats", "parse_query",
        {"question": question, "competition_names": comp_names, "major_names": major_names},
    )
    data, mode, used = T.llm_json(system, user, fallback=lambda: T.rule_parse_stats(db, question))
    merged = dict(T.rule_parse_stats(db, question))
    for k, v in data.items():
        if v not in (None, "", [], {}):
            merged[k] = v
    if not merged.get("dimension"):
        merged["dimension"] = "year"
    return {
        "filters": merged,
        "structured": {"stats_params": merged},
        "trace": [trace_entry("parse_query", node_title("stats", "parse_query"),
                              f"统计维度：{_STATS_DIM_LABEL.get(str(merged.get('dimension')), merged.get('dimension'))}，"
                              f"筛选条件：{T.to_stats_filter(merged).describe()}")],
        **_mode_fields(state, used, mode),
    }


def _stats_detail(stats: StatsService, dimension: str, flt: StatsFilter, chart_kind: str) -> list[dict[str, Any]]:
    if chart_kind == "workload" or dimension == "workload":
        return stats.teacher_workload(flt)
    return {
        "year": stats.by_year, "competition": stats.by_competition, "major": stats.by_major,
        "teacher": stats.by_teacher, "student": stats.by_student,
        "award_level": stats.by_award_level, "level": stats.by_level,
    }.get(dimension, stats.by_year)(flt)


def _stats_query(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    params = dict(state.get("filters") or {})
    flt = T.to_stats_filter(params)
    stats = StatsService(db)
    overview = stats.overview(flt)
    dimension = str(params.get("dimension") or "year")
    chart_kind = str(params.get("chart") or "trend")
    detail = _stats_detail(stats, dimension, flt, chart_kind)
    cols = _STATS_COLUMNS.get("workload" if chart_kind == "workload" else dimension) or _STATS_COLUMNS["year"]
    tables = [
        _table("总览", [("k", "指标"), ("v", "数值")], [
            {"k": "参赛队数", "v": overview.get("registrations")},
            {"k": "参赛人次", "v": overview.get("participants")},
            {"k": "获奖数量", "v": overview.get("awards")},
            {"k": "获奖率(%)", "v": overview.get("award_rate")},
            {"k": "高等级奖(特等/一等)", "v": overview.get("high_level_awards")},
            {"k": "涉及学生数", "v": overview.get("students")},
            {"k": "指导教师数", "v": overview.get("teachers")},
            {"k": "涉及赛事数", "v": overview.get("competitions")},
        ]),
    ]
    if detail:
        tables.append(_table(f"按{_STATS_DIM_LABEL.get(dimension, dimension)}统计", cols, detail))
    if dimension != "year":
        year_rows = stats.by_year(flt)
        if year_rows:
            tables.append(_table("年度趋势", _STATS_COLUMNS["year"], year_rows))
    return {
        "structured": {**(state.get("structured") or {}), "overview": overview, "detail": detail,
                       "dimension": dimension, "chart_kind": chart_kind},
        "tables": tables,
        "trace": [trace_entry("query", node_title("stats", "query"),
                              f"聚合得到 {len(detail)} 行{_STATS_DIM_LABEL.get(dimension, dimension)}明细，"
                              f"获奖率 {overview.get('award_rate')}%")],
    }


def _stats_chart(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db = _db(config)
    structured = state.get("structured") or {}
    kind = str(structured.get("chart_kind") or "trend")
    flt = T.to_stats_filter(state.get("filters") or {})
    try:
        option = StatsService(db).chart(kind, flt)
    except Exception:  # noqa: BLE001 - 图表失败不影响数据表与结论
        option = {}
    charts = [{"kind": kind, "title": (option.get("title") or {}).get("text") or "统计图表", "option": option}] if option else []
    return {
        "charts": charts,
        "trace": [trace_entry("chart", node_title("stats", "chart"),
                              f"生成 ECharts 配置：{kind}") if charts else
                  trace_entry("chart", node_title("stats", "chart"), "无可用图表配置", level="warning")],
    }


def _stats_answer(overview: dict[str, Any], detail: list[dict[str, Any]], dimension: str) -> str:
    if not overview.get("registrations") and not overview.get("awards"):
        return (
            f"该条件下无数据（统计口径：{overview.get('filter')}）。\n\n"
            "建议放宽条件，例如去掉年份限制、改用赛事简称，或先到「赛事台账」补充登记与获奖数据。"
        )
    cols = _STATS_COLUMNS.get(dimension) or _STATS_COLUMNS["year"]
    parts = [
        f"**统计口径**：{overview.get('filter')}（数据来源：竞赛台账，统计时间截至当日）",
        "",
        "**关键结论**",
        f"- 共 {overview.get('registrations')} 支队伍参赛，涉及 {overview.get('participants')} 人次、"
        f"{overview.get('students')} 名学生、{overview.get('teachers')} 名指导教师，覆盖 {overview.get('competitions')} 个赛事；",
        f"- 获奖 {overview.get('awards')} 项，获奖率 {overview.get('award_rate')}%，"
        f"其中特等奖/一等奖 {overview.get('high_level_awards')} 项；",
    ]
    if detail:
        top = detail[0]
        if dimension == "year":
            years = [str(d.get("year")) for d in detail]
            parts.append(f"- 年度范围：{'、'.join(years)}；"
                         f"参赛最多的是 {top.get('year')} 年（{top.get('registrations')} 队）。")
        elif dimension == "competition":
            parts.append(f"- 参与度最高的赛事是「{top.get('competition_name')}」"
                         f"（{top.get('registrations')} 队，获奖 {top.get('awards')} 项）。")
        elif dimension == "major":
            parts.append(f"- 参赛最多的专业是「{top.get('major')}」"
                         f"（{top.get('registrations')} 队，获奖率 {top.get('award_rate')}%）。")
        elif dimension == "teacher":
            parts.append(f"- 指导工作量最多的是「{top.get('teacher')}」"
                         f"（指导 {top.get('registrations')} 队，获奖 {top.get('awards')} 项）。")
        else:
            parts.append(f"- 排名第一：{top.get('award_level') or top.get('teacher') or top.get('student')}"
                         f"（{top.get('count') or top.get('registrations') or top.get('workload')}）。")
    parts += ["", f"**按{_STATS_DIM_LABEL.get(dimension, dimension)}明细**", _rows_to_markdown(cols, detail)]
    return "\n".join(parts)


def _stats_compose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    structured = state.get("structured") or {}
    overview = structured.get("overview") or {}
    detail = structured.get("detail") or []
    dimension = str(structured.get("dimension") or "year")
    cols = _STATS_COLUMNS.get(dimension) or _STATS_COLUMNS["year"]
    values = {
        "answer_rules": "\n".join(f"- {r}" for r in answer_rules("stats")),
        "structured_filter": T.format_structured(overview.get("filter_detail") or {}, 800),
        "structured_overview": T.format_structured(overview, 1200),
        "structured_detail": _rows_to_markdown(cols, detail[:30]),
    }
    system, user = build_prompt("stats", "compose", values)
    text, ok = T.llm_text(system, user, temperature=0.2)
    used = False
    mode = "offline"
    if ok:
        answer = text
        used, mode = True, get_llm().provider
    else:
        answer = _stats_answer(overview, detail, dimension)
    return {
        "answer": answer,
        "sections": [_md("统计结论", answer)],
        "trace": [trace_entry("compose", node_title("stats", "compose"), f"生成统计结论（{len(answer)} 字）")],
        **_mode_fields(state, used, mode),
    }


# ============================================================
#  图注册表
# ============================================================

GRAPH_SPECS: dict[str, dict[str, Any]] = {
    "qa": {
        "nodes": ["understand", "retrieve", "structured_lookup", "grade", "synthesize", "fallback"],
        "edges": [("START", "understand"), ("understand", "retrieve"), ("structured_lookup", "grade"),
                  ("synthesize", "END"), ("fallback", "END")],
        "branches": [("retrieve", _qa_route_after_retrieve,
                      {"structured_lookup": "structured_lookup", "fallback": "fallback"}),
                     ("grade", _qa_route_after_grade,
                      {"retrieve": "retrieve", "synthesize": "synthesize"})],
        "builders": {
            "understand": qa_understand, "retrieve": qa_retrieve,
            "structured_lookup": qa_structured_lookup, "grade": qa_grade,
            "synthesize": qa_synthesize, "fallback": qa_fallback,
        },
    },
    "recommend": {
        "nodes": ["parse_profile", "score", "enrich_kb", "synthesize"],
        "edges": [("START", "parse_profile"), ("parse_profile", "score"), ("score", "enrich_kb"),
                  ("enrich_kb", "synthesize"), ("synthesize", "END")],
        "builders": {"parse_profile": _recommend_parse_profile, "score": _recommend_score,
                     "enrich_kb": _recommend_enrich, "synthesize": _recommend_synthesize},
    },
    "prep": {
        "nodes": ["resolve_event", "build_plan", "retrieve_materials", "synthesize"],
        "edges": [("START", "resolve_event"), ("resolve_event", "build_plan"), ("build_plan", "retrieve_materials"),
                  ("retrieve_materials", "synthesize"), ("synthesize", "END")],
        "builders": {"resolve_event": _prep_resolve_event, "build_plan": _prep_build_plan,
                     "retrieve_materials": _prep_retrieve, "synthesize": _prep_synthesize},
    },
    "review": {
        "nodes": ["prepare_text", "rule_check", "llm_suggest", "compose"],
        "edges": [("START", "prepare_text"), ("prepare_text", "rule_check"), ("rule_check", "llm_suggest"),
                  ("llm_suggest", "compose"), ("compose", "END")],
        "builders": {"prepare_text": _review_prepare, "rule_check": _review_rule_check,
                     "llm_suggest": _review_llm_suggest, "compose": _review_compose},
    },
    "budget": {
        "nodes": ["parse_params", "compute", "policy_lookup", "compose"],
        "edges": [("START", "parse_params"), ("parse_params", "compute"), ("compute", "policy_lookup"),
                  ("policy_lookup", "compose"), ("compose", "END")],
        "builders": {"parse_params": _budget_parse, "compute": _budget_compute,
                     "policy_lookup": _budget_policy_lookup, "compose": _budget_compose},
    },
    "loan": {
        "nodes": ["load_budget", "compute", "compose"],
        "edges": [("START", "load_budget"), ("load_budget", "compute"), ("compute", "compose"),
                  ("compose", "END")],
        "builders": {"load_budget": _loan_load_budget, "compute": _loan_compute, "compose": _loan_compose},
    },
    "reimbursement": {
        "nodes": ["parse_items", "compute", "compose"],
        "edges": [("START", "parse_items"), ("parse_items", "compute"), ("compute", "compose"),
                  ("compose", "END")],
        "builders": {"parse_items": _reimb_parse_items, "compute": _reimb_compute, "compose": _reimb_compose},
    },
    "stats": {
        "nodes": ["parse_query", "query", "chart", "compose"],
        "edges": [("START", "parse_query"), ("parse_query", "query"), ("query", "chart"),
                  ("chart", "compose"), ("compose", "END")],
        "builders": {"parse_query": _stats_parse, "query": _stats_query,
                     "chart": _stats_chart, "compose": _stats_compose},
    },
}

_COMPILED: dict[str, Any] = {}


def get_graph(agent: str):
    """获取（并缓存）某个智能体的已编译工作流。"""
    if agent not in GRAPH_SPECS:
        raise KeyError(f"未知智能体：{agent}，可选值：{sorted(GRAPH_SPECS)}")
    if agent not in _COMPILED:
        spec = GRAPH_SPECS[agent]
        _COMPILED[agent] = _mk_graph(
            agent, spec["builders"], spec["edges"], branches=spec.get("branches")
        )
    return _COMPILED[agent]


def validate_graphs() -> list[str]:
    """校验代码图结构与 prompts/*.yaml 声明一致，返回问题列表。"""
    specs = {agent: {"nodes": spec["nodes"]} for agent, spec in GRAPH_SPECS.items()}
    return validate_registry(specs)


def graph_overview() -> list[dict[str, Any]]:
    """输出全部智能体的节点与边，供「工作流总览」页面与文档使用。"""
    from .prompts import load_agent_config

    out: list[dict[str, Any]] = []
    for agent, spec in GRAPH_SPECS.items():
        cfg = load_agent_config(agent)
        out.append({
            "agent": agent,
            "name": cfg.get("name") or AGENT_LABELS.get(agent, agent),
            "description": cfg.get("description", ""),
            "mode": cfg.get("mode", ""),
            "nodes": [
                {"id": n, "title": node_title(agent, n), "desc": (cfg_node.get("desc") or "")}
                for n in spec["nodes"]
                for cfg_node in [next((x for x in cfg.get("nodes", []) if str(x.get("id")) == n), {})]
            ],
            "edges": [{"from": a, "to": b} for a, b in spec["edges"]]
            + [{"from": a, "to": t, "when": "条件路由"} for a, _, mapping in spec.get("branches") or []
               for t in mapping.values()],
            "answer_rules": cfg.get("answer_rules", []),
        })
    return out