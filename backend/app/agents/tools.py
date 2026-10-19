"""智能体工具集。

两类工具：
  1. LLM 工具：JSON 结构化抽取、文本生成 —— 配置了大模型时使用；
  2. 规则工具：离线解析与检索 —— 未配置大模型时同样可用，保证系统零配置可运行。
两条路径产出同一份数据结构，因此上层工作流与前端界面完全一致。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Competition, Major, Student, Teacher
from ..llm import get_llm
from ..nlp import split_sentences, tokenize, truncate
from ..rag import HybridRetriever, RetrievedChunk
from ..services.stats_service import StatsFilter

# ============================================================
#  LLM 辅助
# ============================================================
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中稳健地提取 JSON 对象。"""
    if not text:
        return {}
    candidates: list[str] = []
    m = _JSON_BLOCK.search(text)
    if m:
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text.strip())
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return {}


def llm_available() -> bool:
    try:
        return get_llm().is_available
    except Exception:  # noqa: BLE001
        return False


def llm_json(
    system: str,
    user: str,
    *,
    fallback: Callable[[], dict[str, Any]] | None = None,
    temperature: float = 0.1,
) -> tuple[dict[str, Any], str, bool]:
    """调用大模型做结构化抽取；失败或不可用时回退到规则解析。

    返回 (数据, 使用的模式, 是否真的调用了大模型)
    """
    llm = get_llm()
    if not llm.is_available:
        return (fallback() if fallback else {}), "offline", False
    try:
        resp = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            json_mode=True,
        )
        data = extract_json(resp.content)
        if data:
            return data, llm.provider, True
        raise ValueError("模型未返回可解析的 JSON")
    except Exception:  # noqa: BLE001 - 任何模型异常都回退到离线路径，保证可用性
        return (fallback() if fallback else {}), "offline", False


def llm_text(system: str, user: str, *, temperature: float = 0.3, max_tokens: int | None = None) -> tuple[str, bool]:
    llm = get_llm()
    if not llm.is_available:
        return "", False
    try:
        resp = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.content.strip(), bool(resp.content.strip())
    except Exception:  # noqa: BLE001
        return "", False


# ============================================================
#  知识库检索工具
# ============================================================
def kb_search(
    db: Session,
    queries: list[str],
    *,
    top_k: int = 6,
    filters: dict[str, Any] | None = None,
) -> list[RetrievedChunk]:
    retriever = HybridRetriever(db)
    queries = [q for q in (queries or []) if q and q.strip()]
    if not queries:
        return []
    if len(queries) == 1:
        return retriever.retrieve(queries[0], top_k=top_k, filters=filters)
    return retriever.retrieve_multi(queries, top_k=top_k, filters=filters)


def format_evidence(chunks: list[RetrievedChunk], *, max_chars: int = 4200) -> str:
    if not chunks:
        return "（未检索到相关知识库内容）"
    lines: list[str] = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        loc = c.section or ""
        if c.page_no:
            loc = f"{loc} 第{c.page_no}页".strip()
        head = f"[^ {i} ] 文件《{c.document_title}》" + (f"（{loc}）" if loc else "")
        body = truncate(c.content.replace("\n", " "), 700)
        block = f"{head}\n{body}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n\n".join(lines)


def build_citations(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [c.citation(i) for i, c in enumerate(chunks, start=1)]


def kb_stats(db: Session) -> dict[str, Any]:
    return HybridRetriever(db).stats()


# ============================================================
#  离线规则解析
# ============================================================
YEAR_RE = re.compile(r"(20\d{2})\s*年?")
AWARD_LEVELS = ["特等奖", "一等奖", "二等奖", "三等奖", "优胜奖", "入围奖"]
LEVEL_WORDS = {
    "国家级": ["国家级", "国赛", "国家", "全国"],
    "省级": ["省级", "省赛", "省"],
    "校级": ["校级", "校赛", "校内"],
}
INTENT_RULES = [
    ("报名条件", ["报名条件", "参赛资格", "资格要求", "谁可以参加", "能不能参加", "组队", "几个人"]),
    ("时间节点", ["时间", "截止", "什么时候", "日期", "报名开始", "赛程", "节点"]),
    ("材料要求", ["材料", "提交", "作品要求", "需要准备", "格式", "字数", "页数"]),
    ("奖项设置", ["奖项", "获奖比例", "奖金", "证书", "一等奖", "评分标准"]),
    ("经费制度", ["经费", "预算", "报销", "借款", "差旅", "住宿", "补助", "发票", "费用标准",
                  "报名费", "参赛费", "收费", "费用"]),
    ("数据统计", ["统计", "多少", "数量", "排名", "获奖情况", "历年", "趋势", "对比"]),
    ("赛事信息", ["是什么", "介绍", "主办", "简介", "官网", "级别", "属于"]),
]


def list_competition_names(db: Session) -> list[str]:
    rows = db.execute(select(Competition.name, Competition.short_name)).all()
    out: list[str] = []
    for name, short in rows:
        if name:
            out.append(name)
        if short:
            out.append(short)
    return out


def _known_values(db: Session) -> dict[str, list[str]]:
    return {
        "majors": [m for (m,) in db.execute(select(Major.name)).all() if m],
        "teachers": [t for (t,) in db.execute(select(Teacher.name)).all() if t],
        "students": [s for (s,) in db.execute(select(Student.name)).all() if s],
        "competitions": list_competition_names(db),
    }


def rule_parse_question(db: Session, question: str, history: str = "") -> dict[str, Any]:
    """离线的问题理解：意图识别、赛事与年份抽取、检索查询扩展。"""
    q = question or ""
    known = _known_values(db)

    competition = ""
    for name in sorted(known["competitions"], key=len, reverse=True):
        if name and name in q:
            competition = name
            break

    years = [int(y) for y in YEAR_RE.findall(q)]

    intent = "其他"
    for name, keywords in INTENT_RULES:
        if any(k in q for k in keywords):
            intent = name
            break

    queries: list[str] = [q]
    if competition and competition not in q:
        queries.append(f"{competition} {q}")
    if years:
        queries.append(f"{years[0]}年 {q}")
    # 同义词扩展
    synonyms = {
        "报名费": "报名费 参赛费 会务费 收费",
        "报名费多少": "报名费 参赛费 收费标准",
        "报名时间": "报名时间 报名截止 报名起止",
        "材料": "提交材料 作品要求 参赛材料",
        "奖项": "奖项设置 获奖比例 奖励",
        "住宿": "住宿费 住宿标准 差旅",
        "报销": "报销 票据 发票 财务",
    }
    for key, expansion in synonyms.items():
        if key in q:
            queries.append(expansion)
    if intent == "经费制度":
        queries.append("学科竞赛经费管理办法 开支范围 报销流程")
    if intent == "奖项设置" and competition:
        queries.append(f"{competition} 奖项 获奖比例")

    need_structured = intent in {"数据统计", "奖项设置", "赛事信息"} and bool(
        re.search(r"(多少|几|数量|统计|排名|比例|获奖率)", q)
    )
    return {
        "intent": intent,
        "competition": competition,
        "year": years[0] if years else None,
        "queries": list(dict.fromkeys(queries))[:4],
        "need_knowledge": True,
        "need_structured": need_structured,
    }


def rule_parse_stats(db: Session, question: str) -> dict[str, Any]:
    """离线统计查询解析：自然语言 → 筛选条件 + 统计维度 + 图表类型。"""
    q = question or ""
    known = _known_values(db)

    years = [int(y) for y in YEAR_RE.findall(q)]
    if not years:
        span = re.search(r"近\s*([二两三四五六七八九十\d]+)\s*年|最近\s*([二两三四五六七八九十\d]+)\s*年", q)
        if span:
            raw = span.group(1) or span.group(2) or ""
            numeric = {"二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                       "七": 7, "八": 8, "九": 9, "十": 10}
            count = int(raw) if raw.isdigit() else numeric.get(raw, 0)
            if count:
                end = date.today().year
                years = list(range(end - count + 1, end + 1))
    award_levels = [lv for lv in AWARD_LEVELS if lv in q]
    levels: list[str] = []
    for canonical, words in LEVEL_WORDS.items():
        if any(w in q for w in words):
            levels.append(canonical)
    competitions = [c for c in sorted(known["competitions"], key=len, reverse=True) if c and c in q]
    majors = [m for m in sorted(known["majors"], key=len, reverse=True) if m and m in q]
    teachers = [t for t in known["teachers"] if t and len(t) >= 2 and t in q]
    students = [s for s in known["students"] if s and len(s) >= 2 and s in q]

    dimension = "year"
    dim_rules = [
        ("teacher", ["教师", "老师", "指导老师", "指导教师"]),
        ("student", ["学生", "同学", "个人"]),
        ("major", ["专业", "系"]),
        ("competition", ["赛事", "赛项", "比赛", "竞赛"]),
        ("award_level", ["获奖等级", "奖项等级", "等级分布"]),
        ("level", ["赛事级别", "竞赛级别", "国家级省级"]),
    ]
    for dim, words in dim_rules:
        if any(w in q for w in words):
            dimension = dim
            break

    chart_map = {
        "year": "trend",
        "competition": "competition",
        "major": "major",
        "teacher": "teacher",
        "student": "teacher",
        "award_level": "award_level",
        "level": "level",
    }
    chart = chart_map.get(dimension)
    if "工作量" in q or "学时" in q:
        chart = "workload"
        dimension = "teacher"
    if "比例" in q or "构成" in q or "占比" in q:
        chart = "award_level" if award_levels or "奖" in q else chart

    keyword = ""
    for token in tokenize(q):
        if len(token) >= 3 and token not in {"统计", "查询", "多少", "情况"}:
            keyword = ""
            break

    return {
        "years": years,
        "competitions": competitions,
        "levels": levels,
        "categories": [],
        "award_levels": award_levels,
        "majors": majors,
        "teachers": teachers,
        "students": students,
        "keyword": keyword,
        "dimension": dimension,
        "chart": chart,
        "intent": "统计查询",
    }


def to_stats_filter(parsed: dict[str, Any]) -> StatsFilter:
    return StatsFilter(
        years=[int(y) for y in (parsed.get("years") or [])],
        competitions=[str(x) for x in (parsed.get("competitions") or [])],
        levels=[str(x) for x in (parsed.get("levels") or [])],
        categories=[str(x) for x in (parsed.get("categories") or [])],
        award_levels=[str(x) for x in (parsed.get("award_levels") or [])],
        majors=[str(x) for x in (parsed.get("majors") or [])],
        teachers=[str(x) for x in (parsed.get("teachers") or [])],
        students=[str(x) for x in (parsed.get("students") or [])],
        keyword=str(parsed.get("keyword") or ""),
    )


# ---------- 预算要素解析 ----------
CATEGORY_KEYWORDS = {
    "报名费": ["报名费", "参赛费", "会务费", "注册费"],
    "交通费": ["交通", "高铁", "动车", "火车", "飞机", "机票", "车票", "往返", "包车"],
    "住宿费": ["住宿", "宾馆", "酒店", "住"],
    "伙食补助": ["伙食", "餐补", "补助", "餐饮"],
    "市内交通": ["市内", "打车", "地铁", "公交", "出租车"],
    "耗材费": ["耗材", "元器件", "材料费", "物料", "打印", "刻录"],
    "测试费": ["测试", "检测", "认证", "加工"],
    "图书资料费": ["图书", "资料", "文献"],
    "培训费": ["培训", "集训"],
    "劳务费": ["劳务", "专家费", "评审费"],
}


def rule_parse_budget(db: Session, question: str, payload: dict[str, Any], event_info: dict[str, Any]) -> dict[str, Any]:
    q = question or ""
    out: dict[str, Any] = dict(payload or {})

    if not out.get("competition_name"):
        for name in sorted(list_competition_names(db), key=len, reverse=True):
            if name and name in q:
                out["competition_name"] = name
                break
    if out.get("competition_name") and not out.get("competition_level"):
        comp = db.execute(
            select(Competition).where(Competition.name == out["competition_name"])
        ).scalars().first()
        if comp:
            out["competition_level"] = comp.level

    if not out.get("student_count"):
        m = re.search(r"(\d+)\s*(?:名|个|位)?\s*学生", q) or re.search(r"(\d+)\s*人", q)
        if m:
            out["student_count"] = int(m.group(1))
    if not out.get("teacher_count"):
        m = re.search(r"(\d+)\s*(?:名|个|位)?\s*(?:指导)?(?:教师|老师)", q)
        if m:
            out["teacher_count"] = int(m.group(1))
    if "不随队" in q or "不参加" in q:
        out.setdefault("mentor_trip", False)

    if not out.get("destination"):
        m = re.search(r"(?:去|在|地点|目的地|赛区)[：: ]*([\u4e00-\u9fff]{2,10})", q)
        if m:
            out["destination"] = m.group(1)

    if not out.get("trip_days"):
        m = re.search(r"(\d+)\s*天", q)
        if m:
            out["trip_days"] = int(m.group(1))

    if out.get("registration_fee") in (None, ""):
        m = re.search(r"报名费\s*([\d.]+)\s*元\s*(?:/|每)?\s*(人|队)?", q)
        if not m:
            m = re.search(r"([\d.]+)\s*元\s*(?:/|每)\s*(?:人|队)", q)
        if m:
            out["registration_fee"] = float(m.group(1))
            unit = m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else "人"
            out.setdefault("registration_fee_unit", "元/人" if unit == "人" else "元/队")

    if event_info:
        # 届次数据中的报名费优先于通用费用标准，0 元也视为「免费」的明确信息
        if out.get("registration_fee") in (None, ""):
            fee = event_info.get("registration_fee")
            if fee is not None:
                out["registration_fee"] = float(fee)
                out["registration_fee_unit"] = event_info.get("registration_fee_unit") or "元/人"
        if not out.get("year") and event_info.get("year"):
            out["year"] = event_info["year"]
        out.setdefault("state", event_info)

    return out


# ---------- 报销明细解析 ----------
AMOUNT_RE = re.compile(r"([\d]+(?:\.\d{1,2})?)\s*(?:元|块钱|块|¥)")
DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})|(\d{1,2})月(\d{1,2})日")
INVOICE_RE = re.compile(r"发票(?:号|号码|编号)?[：:\s]*([0-9A-Za-z]{6,})")
NO_INVOICE_RE = re.compile(r"(无票|没有发票|无发票|未取得发票)")


def _guess_category(text: str) -> str:
    for category, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            return category
    return "其他"


def _parse_date_in(text: str) -> str:
    m = DATE_RE.search(text)
    if not m:
        return ""
    if m.group(1):
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    year = __import__("datetime").date.today().year
    return f"{year:04d}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"


def rule_parse_expenses(db: Session, question: str, payload: dict[str, Any]) -> dict[str, Any]:
    """离线解析支出明细：支持逐行文本，也支持结构化数组。"""
    out: dict[str, Any] = dict(payload or {})
    items: list[dict[str, Any]] = [i for i in (out.get("items") or []) if isinstance(i, dict)]

    text = question or out.get("text") or ""
    if text and not items:
        for raw_line in re.split(r"[\n；;]", text):
            line = raw_line.strip()
            if not line or len(line) < 3:
                continue
            m = AMOUNT_RE.search(line)
            if not m:
                continue
            amount = float(m.group(1))
            if amount <= 0:
                continue
            name = AMOUNT_RE.sub("", line)
            name = INVOICE_RE.sub("", name)
            name = DATE_RE.sub("", name).strip(" ,，。.、:：-")
            items.append(
                {
                    "category": _guess_category(line),
                    "item_name": truncate(name, 40) or _guess_category(line),
                    "amount": amount,
                    "expense_date": _parse_date_in(line),
                    "invoice_no": (INVOICE_RE.search(line).group(1) if INVOICE_RE.search(line) else ""),
                    "has_invoice": not bool(NO_INVOICE_RE.search(line)),
                    "payee": "",
                    "remark": "",
                }
            )
    out["items"] = items

    if not out.get("claimant_name"):
        m = re.search(r"报销人[：: ]*([\u4e00-\u9fff]{2,4})", text)
        if m:
            out["claimant_name"] = m.group(1)
    if not out.get("competition_name"):
        for name in sorted(set(list_competition_names(db)), key=len, reverse=True):
            if name and name in text:
                out["competition_name"] = name
                break
    return out


def rule_parse_loan(db: Session, question: str, payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(payload or {})
    q = question or ""
    if not out.get("budget_doc_no"):
        m = re.search(r"(YS\d{6,})", q)
        if m:
            out["budget_doc_no"] = m.group(1)
    if out.get("amount") is None:
        m = re.search(r"(?:借款|借)\s*([\d.]+)\s*元", q)
        if m:
            out["amount"] = float(m.group(1))
    if not out.get("borrower_name"):
        m = re.search(r"借款人[：: ]*([\u4e00-\u9fff]{2,4})", q)
        if m:
            out["borrower"] = {"name": m.group(1)}
    if not out.get("purpose"):
        m = re.search(r"用途[：: ]*([^\n，。;；]{2,40})", q)
        if m:
            out["purpose"] = m.group(1)
    return out


# ============================================================
#  离线文本合成
# ============================================================
_TABLE_SEPARATOR = re.compile(r"^:?-{2,}:?$")


_TABLE_HEADERS = {
    "赛事", "费用类别", "获奖级别", "阶段", "项目", "类别", "序号", "时间节点",
    "指标", "检查项", "材料", "奖项", "级别", "赛道", "事项",
}


def _table_rows(text: str) -> list[str]:
    """把 Markdown 表格行补充表头后转为可检索的陈述，避免“住宿费/国家级”跨行丢上下文。"""
    # 分块器把句子直接拼接时，表格换行会退化为 ||；这里先行还原。
    normalized = re.sub(r"\|\|+", "|\n|", text or "")
    out: list[str] = []
    header: list[str] | None = None
    for raw in normalized.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            pos = line.find("|")
            if pos < 0:
                header = None
                continue
            line = line[pos:]
        if not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and all(_TABLE_SEPARATOR.match(c.replace(" ", "")) for c in cells if c):
            continue
        if not any(cells):
            continue
        if header is None:
            if cells[0] in _TABLE_HEADERS:
                header = cells
            else:
                out.append("；".join(c for c in cells if c))
            continue
        if len(cells) != len(header):
            header = None
            continue
        pairs = [
            f"{head} {cell}".strip()
            for head, cell in zip(header[1:], cells[1:])
            if cell and cell not in {"-", "—", "/"}
        ]
        label = next((c for c in cells if c), "")
        if label and pairs:
            out.append(f"{label}：" + "；".join(pairs))
        elif label:
            out.append(label)
    return out


def extractive_answer(question: str, chunks: list[RetrievedChunk], *, max_points: int = 6) -> str:
    """无大模型时的抽取式回答：按问题词的稀有度加权挑选原文句与表格行，并保留引用编号。"""
    if not chunks:
        return ""

    q_tokens = set(tokenize(question))
    if not q_tokens:
        return ""
    # 「国赛/省赛/校赛」与正文中的「全国决赛/省级/校级」不是同一字符串，匹配前先归一
    if re.search(r"国赛|国家级|全国", question):
        q_tokens.update({"国家级", "全国", "决赛"})
    elif re.search(r"省赛|省级|省大学生", question):
        q_tokens.update({"省级", "省赛"})
    elif re.search(r"校赛|校级", question):
        q_tokens.update({"校级", "校赛"})

    candidates: list[tuple[int, int, float, str, bool]] = []
    for i, chunk in enumerate(chunks, start=1):
        seen_in_chunk: set[str] = set()
        doc_title = (chunk.document_title or "").strip()
        section = (chunk.section or "").strip()
        for row in _table_rows(chunk.content):
            key = row[:24]
            if len(row) >= 8 and key not in seen_in_chunk:
                seen_in_chunk.add(key)
                candidates.append((i, chunk.document_id, chunk.score, row, True))
        for sent in split_sentences(chunk.content):
            sent = sent.strip()
            if len(sent) < 10 or sent.startswith("|") or sent.count("|") >= 2:
                continue
            # 跳过文档标题、章节标题与资料说明等无信息量文本
            if sent in {doc_title, section} or sent.startswith("本资料依据"):
                continue
            if re.fullmatch(r"[一二三四五六七八九十百]+[、.．]\s*[^。；;，,]{2,30}", sent):
                continue
            key = sent[:24]
            if key in seen_in_chunk:
                continue
            seen_in_chunk.add(key)
            candidates.append((i, chunk.document_id, chunk.score, sent, False))

    if not candidates:
        return ""

    token_sets: list[set[str]] = []
    doc_freq: Counter[str] = Counter()
    doc_best: dict[int, float] = {}
    for _, doc_id, chunk_score, text, _ in candidates:
        tokens = set(tokenize(text))
        token_sets.append(tokens)
        doc_freq.update(q_tokens & tokens)
        doc_best[doc_id] = max(doc_best.get(doc_id, 0.0), chunk_score)
    top_doc_score = max(doc_best.values())
    focused_docs = {doc_id for doc_id, score in doc_best.items() if score >= top_doc_score * 0.95}

    total = len(candidates)
    weights = {t: math.log((total + 1) / (doc_freq.get(t, 0) + 1)) + 1.0 for t in q_tokens}
    total_weight = sum(weights.values()) or 1.0
    asks_number = bool(re.search(r"多少|几个|几天|上限|标准|比例|费用|金额|学时|积分|人数|数量", question))
    level_hint = ""
    if re.search(r"国赛|国家级|全国", question):
        level_hint = "national"
    elif re.search(r"省赛|省级|省大学生", question):
        level_hint = "provincial"
    elif re.search(r"校赛|校级", question):
        level_hint = "school"
    level_words = {
        "national": {"国赛", "国家级", "全国", "决赛"},
        "provincial": {"省赛", "省级"},
        "school": {"校赛", "校级"},
    }

    scored: list[tuple[float, int, str, bool]] = []
    for (idx, doc_id, chunk_score, text, is_table), tokens in zip(candidates, token_sets):
        if doc_id not in focused_docs:
            continue
        matched = q_tokens & tokens
        if not matched:
            continue
        coverage = sum(weights[t] for t in matched) / total_weight
        density = len(matched) / max(len(tokens), 1)
        number_bonus = (0.6 if asks_number else 0.25) if re.search(r"\d", text) else 0.0
        score = coverage * 4 + min(len(matched), 4) * 0.15 + density * 0.6
        score += chunk_score * 0.4 + number_bonus + (0.12 if is_table else 0.0)
        if level_hint:
            if tokens & level_words[level_hint]:
                score += 0.9
            elif any(tokens & words for lv, words in level_words.items() if lv != level_hint):
                score -= 0.9
        scored.append((score, idx, text, is_table))

    scored.sort(key=lambda x: -x[0])
    picked: list[tuple[int, str]] = []
    used_in_chunk: Counter[int] = Counter()
    seen: set[str] = set()
    cutoff = scored[0][0] * 0.7 if scored else 0
    for score, idx, text, _ in scored:
        if score < cutoff:
            break
        key = re.sub(r"\s+", "", text)[:30]
        if key in seen or used_in_chunk[idx] >= 3:
            continue
        seen.add(key)
        used_in_chunk[idx] += 1
        picked.append((idx, text))
        if len(picked) >= max_points:
            break

    if not picked:
        return ""

    lines = ["**根据知识库原文，整理到以下要点：**", ""]
    for idx, text in picked:
        lines.append(f"- {truncate(text, 240)} [^{idx}]")
    return "\n".join(lines)


def format_structured(data: Any, limit: int = 3000) -> str:
    if not data:
        return "（无）"
    if isinstance(data, str):
        return data
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(data)
    return truncate(text, limit)


def summarize_checks(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return ""
    order = {"error": 0, "warning": 1, "info": 2, "pass": 3}
    label = {"error": "不合规", "warning": "需注意", "info": "提示", "pass": "通过"}
    lines = []
    for c in sorted(checks, key=lambda x: order.get(str(x.get("level")), 9)):
        lines.append(f"- [{label.get(str(c.get('level')), '')}] {c.get('message')}")
        if c.get("suggestion"):
            lines.append(f"  建议：{c['suggestion']}")
    return "\n".join(lines)


def text_block(title: str, content: str) -> str:
    return f"\n\n### {title}\n\n{content}" if content else ""


def references_block(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return ""
    lines = ["", "---", "", "### 参考资料"]
    for c in citations:
        loc = c.get("location") or ""
        lines.append(
            f"- [^{c['index']}] 《{c['title']}》" + (f"（{loc}）" if loc else "")
            + (f"　类型：{c['doc_type']}" if c.get("doc_type") else "")
            + (f"　文件：{Path(c['source_path']).name}" if c.get("source_path") else "")
        )
    return "\n".join(lines)