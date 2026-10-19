"""8 个智能体工作流的冒烟测试。

用法：.venv/Scripts/python.exe scripts/smoke_agents.py
不依赖外部大模型；离线规则通道应全部通过。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.runner import run_agent, validate_all  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Budget  # noqa: E402
from app.services.finance_service import FinanceService  # noqa: E402
from sqlalchemy import select  # noqa: E402

BUDGET_DOC_NO = "YS-SMOKE-001"
BUDGET_PAYLOAD = {
    "competition_name": "蓝桥杯",
    "year": 2027,
    "student_count": 5,
    "mentor_trip": False,
    "destination": "杭州",
    "trip_days": 2,
    "transport_mode": "高铁",
}


def ensure_budget(db) -> float:
    budget = db.execute(select(Budget).where(Budget.doc_no == BUDGET_DOC_NO)).scalars().first()
    if budget is None:
        budget = FinanceService(db).create_budget(
            {**BUDGET_PAYLOAD, "doc_no": BUDGET_DOC_NO, "status": "已批准"}, applicant={"name": "王建国"}
        )
        budget.approved_amount = budget.total_amount
        db.commit()
    return float(budget.approved_amount or budget.total_amount or 0)


CASES = [
    ("qa", dict(question="2026 年蓝桥杯的报名截止时间和参赛对象是什么？")),
    ("recommend", dict(
        question="我是软件工程专业大二学生，会 Python 和数据分析，参加过校级项目，推荐参加什么竞赛？",
        profile={"major": "软件工程", "grade": "2025级", "tech_tags": ["Python", "数据分析"],
                 "has_project": True, "project_title": "校园二手交易平台"},
    )),
    ("prep", dict(question="帮我制定蓝桥杯软件赛的备赛计划",
                  payload={"competition_name": "蓝桥杯"})),
    ("review", dict(
        question="帮我检查这份项目申报书",
        payload={"material_type": "项目申报书",
                 "competition_name": "中国国际大学生创新大赛",
                 "text": "项目名称：智农云。本项目面向乡村振兴，"
                         "团队成员共5人。项目创新性强，但尚未说明核心技术方案与数据来源，"
                         "也没有给出经费预算和阶段性目标。"},
    )),
    ("budget", dict(question="参加蓝桥杯全国决赛，5名学生，往返高铁，行程2天，需要申请多少预算？",
                    payload=dict(BUDGET_PAYLOAD))),
    ("loan", dict(question="根据已批准的预算生成借款单",
                  payload={"budget_doc_no": BUDGET_DOC_NO, "borrower": {"name": "王建国", "teacher_no": "T2008"}})),
    ("reimbursement", dict(question="帮我检查这些票据能否报销",
                           payload={"competition_name": "蓝桥杯", "budget_doc_no": BUDGET_DOC_NO, "items": [
                               {"category": "交通费", "item_name": "5人往返高铁", "amount": 1200,
                                "invoice_no": "12345678901234567890", "has_invoice": True,
                                "expense_date": "2026-04-10", "payee": "铁路12306"},
                               {"category": "住宿费", "item_name": "住宿2晚", "amount": 900,
                                "invoice_no": "22345678901234567890", "has_invoice": True,
                                "expense_date": "2026-04-10", "payee": "杭州某酒店"},
                               {"category": "餐费", "item_name": "工作餐", "amount": 600,
                                "has_invoice": False, "expense_date": "2026-04-11", "payee": "某餐馆"},
                           ]})),
    ("stats", dict(question="统计 2026 年各竞赛获奖数量与获奖等级分布")),
]


def short(value, limit=260):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> int:
    rules = validate_all()
    print("Prompt/工作流校验：", "通过" if not rules else rules)
    failures = 0
    with SessionLocal() as db:
        amount = ensure_budget(db)
        print(f"冒烟预算单：{BUDGET_DOC_NO}，批准金额 {amount:.2f} 元")
        for agent, kwargs in CASES:
            result = run_agent(db, agent, **kwargs)
            status = "FAIL" if result.get("error") else "OK"
            if result.get("error"):
                failures += 1
            print(f"\n=== [{status}] {agent} / {result['agent_name']} "
                  f"mode={result['mode']} steps={len(result['steps'])} "
                  f"citations={len(result['citations'])} tables={len(result['tables'])} "
                  f"charts={len(result['charts'])} {result['duration_ms']}ms")
            if result.get("error"):
                print("  error:", result["error"][:400])
            print("  answer:", short(result.get("answer", "")))
            if result.get("tables"):
                table = result["tables"][0]
                print("  table:", table.get("title"), "rows:", len(table.get("rows") or []))
            if result.get("charts"):
                print("  chart:", result["charts"][0].get("title"), result["charts"][0].get("type"))
            if result.get("checks"):
                print("  checks:", short(result["checks"], 180))
            if result.get("citations"):
                print("  cite:", result["citations"][0].get("title"), "|",
                      result["citations"][0].get("location"))
    print("\n结果：", "全部通过" if failures == 0 else f"{failures} 个失败")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
