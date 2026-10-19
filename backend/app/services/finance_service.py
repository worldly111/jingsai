"""竞赛经费业务引擎：预算编制、借款单生成、报销单整理与合规校验。

设计原则：
  - 所有金额计算依据来自数据库中的 expense_standards（费用标准表），
    标准表可由管理员维护，代码中不出现任何硬编码的费用数值；
  - 校验开关与阈值来自 data/rules/finance_policy.yaml；
  - 每一行明细都记录 standard_code 与 calc_basis（计算依据），便于财务审核与
    人工复核，也便于在界面上说明"为什么是这么多钱"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Budget,
    BudgetItem,
    Competition,
    ExpenseStandard,
    Loan,
    Reimbursement,
    ReimbursementItem,
)
from ..nlp import truncate
from .amount import amount_to_chinese
from .policy import finance_policy

LEVEL_ALIASES = {
    "国家级": ["国家级", "国家", "全国", "国赛"],
    "省级": ["省级", "省", "省赛", "区域", "赛区"],
    "校级": ["校级", "校", "校赛"],
}

# 差旅类费用：校内比赛不得列支
TRAVEL_CATEGORIES = {"交通费", "住宿费", "伙食补助", "市内交通"}


@dataclass
class BudgetPlan:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: float = 0.0
    checks: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    generated_text: str = ""
    standards_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "total": round(self.total, 2),
            "total_upper": amount_to_chinese(self.total),
            "checks": self.checks,
            "approval": self.approval,
            "summary": self.summary,
            "generated_text": self.generated_text,
            "standards_used": self.standards_used,
        }


class FinanceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.policy = finance_policy()

    # ==========================================================
    #  费用标准
    # ==========================================================
    def standards(self, *, active_only: bool = True) -> list[ExpenseStandard]:
        stmt = select(ExpenseStandard)
        if active_only:
            stmt = stmt.where(ExpenseStandard.is_active.is_(True))
        return list(self.db.execute(stmt.order_by(ExpenseStandard.category)).scalars())

    def find_standard(self, category: str, level: str = "", region: str = "不限") -> ExpenseStandard | None:
        """按费用类别 + 竞赛级别 + 地区匹配标准，级别精确匹配优先。"""
        rows = [s for s in self.standards() if s.category == category]
        if not rows:
            return None

        def score(s: ExpenseStandard) -> int:
            v = 0
            if s.competition_level == level:
                v += 4
            elif s.competition_level in ("", "不限"):
                v += 1
            if region and s.region == region:
                v += 3
            elif s.region in ("", "不限"):
                v += 1
            return v

        rows = [s for s in rows if s.competition_level in (level, "不限", "") or not level]
        if not rows:
            return None
        rows.sort(key=score, reverse=True)
        return rows[0] if score(rows[0]) > 0 else rows[0]

    def _level_candidates(self, level: str) -> list[str]:
        level = (level or "").strip()
        out = [level]
        for canonical, aliases in LEVEL_ALIASES.items():
            if any(a in level for a in aliases):
                out.append(canonical)
        out.append("不限")
        return [x for x in dict.fromkeys(out) if x]

    # ==========================================================
    #  一、预算编制
    # ==========================================================
    def plan_budget(self, payload: dict[str, Any]) -> BudgetPlan:
        level = str(payload.get("competition_level") or "国家级")
        students = _as_list(payload.get("students"))
        mentors = _as_list(payload.get("mentors"))
        student_count = len(students) or int(payload.get("student_count") or 0)
        mentor_count = len(mentors) or int(payload.get("teacher_count") or 0)

        mentor_trip = bool(payload.get("mentor_trip", True))
        trip_persons = student_count + (mentor_count if mentor_trip else 0)
        trip_days = int(payload.get("trip_days") or 0)
        if trip_days <= 0 and payload.get("start_date") and payload.get("end_date"):
            trip_days = max(_days_between(payload["start_date"], payload["end_date"]), 1)
        nights = max(trip_days - 1, 0)

        destination = str(payload.get("destination") or "")
        region = _region_of(destination)

        plan = BudgetPlan()
        plan.summary = {
            "competition_name": payload.get("competition_name") or "",
            "competition_level": level,
            "track_name": payload.get("track_name") or "",
            "year": payload.get("year"),
            "team_name": payload.get("team_name") or "",
            "student_count": student_count,
            "mentor_count": mentor_count,
            "mentor_trip": mentor_trip,
            "trip_persons": trip_persons,
            "trip_days": trip_days,
            "nights": nights,
            "destination": destination,
            "region": region,
        }

        self._add_registration_fee(plan, payload, level, students, student_count)
        self._add_travel(plan, payload, level, region, trip_persons, trip_days, nights)
        self._add_custom_items(plan, payload)
        self._add_level_checks(plan, level)
        self._finalize(plan, payload)
        return plan

    # ---------- 明细构造 ----------
    def _add_registration_fee(
        self, plan: BudgetPlan, payload: dict[str, Any], level: str, students: list[str], student_count: int
    ) -> None:
        fee = payload.get("registration_fee")
        unit = str(payload.get("registration_fee_unit") or "元/人")
        per_person = payload.get("registration_fee_per_person")
        per_team = payload.get("registration_fee_per_team")

        if per_person is not None:
            fee, unit = float(per_person), "元/人"
        elif per_team is not None:
            fee, unit = float(per_team), "元/队"

        quantity = student_count if unit.endswith("人") else 1

        standard = self.find_standard("报名费", level)
        basis = ""
        if fee is None:
            if standard and standard.value:
                fee = float(standard.value)
                unit = standard.unit or unit
                quantity = student_count if str(standard.unit).endswith("人") else 1
                basis = f"按费用标准 {standard.code}（{standard.name}）计列"
                plan.standards_used.append(standard.code)
            else:
                plan.checks.append(
                    _check(
                        "registration_fee_missing",
                        "warning",
                        "未提供报名费金额，且费用标准库中没有匹配的标准",
                        "请在界面上补充报名费单价，或在费用标准表中新增该赛事的报名费标准",
                    )
                )
                return

        fee = float(fee)
        amount = round(fee * max(quantity, 1), 2)
        if not basis:
            basis = "按赛事通知公布的报名费标准计列"
        if per_person is not None or per_team is not None:
            basis += "（由经办人录入）"

        plan.items.append(
            _item(
                category="报名费",
                item_name=f"{payload.get('competition_name') or '竞赛'}报名费",
                unit=unit,
                quantity=max(quantity, 1),
                unit_price=fee,
                amount=amount,
                standard_code=standard.code if standard else "",
                calc_basis=basis,
                remark=f"{student_count} 名学生" if unit.endswith("人") else "按队计",
            )
        )

    def _add_travel(
        self,
        plan: BudgetPlan,
        payload: dict[str, Any],
        level: str,
        region: str,
        persons: int,
        days: int,
        nights: int,
    ) -> None:
        if persons <= 0 or days <= 0:
            return

        # 交通费：优先采用经办人录入的往返票价，并按标准上限校验
        transport_cap_std = self.find_standard("交通费", level, region)
        transport_unit = payload.get("transport_unit_price")
        if transport_unit is None and transport_cap_std:
            transport_unit = float(transport_cap_std.value)
            note = f"按费用标准 {transport_cap_std.code}（{transport_cap_std.name}）上限估算"
            plan.standards_used.append(transport_cap_std.code)
        elif transport_unit is not None:
            note = "按实际出行方式和站点票价估算（高铁/动车二等座）"
        else:
            transport_unit, note = 0.0, ""

        if transport_unit:
            amount = round(float(transport_unit) * persons, 2)
            over = ""
            if transport_cap_std and float(transport_unit) > float(transport_cap_std.value):
                over = "（超出标准上限，需在说明中注明原因）"
                plan.checks.append(
                    _check(
                        "transport_over_standard",
                        "warning",
                        f"交通费单价 {transport_unit} 元/人 超出标准上限 {transport_cap_std.value} 元/人",
                        "核对出行方式与席别；确需超标的应在预算说明中写明原因",
                    )
                )
            plan.items.append(
                _item(
                    "交通费",
                    f"{payload.get('destination') or '赛区'}往返交通费（{payload.get('transport_mode') or '高铁/动车二等座'}）",
                    unit="元/人（往返）",
                    quantity=persons,
                    unit_price=float(transport_unit),
                    amount=amount,
                    standard_code=transport_cap_std.code if transport_cap_std else "",
                    calc_basis=note + over,
                    remark=f"{persons} 人（含{'指导教师' if persons - int(payload.get('student_count') or 0) > 0 else '仅学生'}）",
                )
            )

        # 住宿费
        hotel_std = self.find_standard("住宿费", level, region)
        if nights > 0 and hotel_std and hotel_std.value:
            amount = round(float(hotel_std.value) * persons * nights, 2)
            plan.standards_used.append(hotel_std.code)
            plan.items.append(
                _item(
                    "住宿费",
                    f"{payload.get('destination') or '赛区'}住宿费",
                    unit="元/人·天",
                    quantity=persons * nights,
                    unit_price=float(hotel_std.value),
                    amount=amount,
                    standard_code=hotel_std.code,
                    calc_basis=(
                        f"{persons} 人 × {nights} 晚 × {hotel_std.value} 元/人·天"
                        f"（标准 {hotel_std.code}，{hotel_std.region}，{hotel_std.unit}，据实报销不超上限）"
                    ),
                    remark="按其他人员标准执行",
                )
            )

        # 伙食补助：按出差自然天数包干
        meal_std = self.find_standard("伙食补助", level, region)
        if meal_std and meal_std.value:
            amount = round(float(meal_std.value) * persons * days, 2)
            plan.standards_used.append(meal_std.code)
            plan.items.append(
                _item(
                    "伙食补助",
                    "竞赛期间伙食补助",
                    unit="元/人·天",
                    quantity=persons * days,
                    unit_price=float(meal_std.value),
                    amount=amount,
                    standard_code=meal_std.code,
                    calc_basis=f"{persons} 人 × {days} 天 × {meal_std.value} 元/人·天，包干使用",
                    remark="由接待单位安排伙食的不得重复领取",
                )
            )

        # 市内交通费
        local_std = self.find_standard("市内交通", level, region)
        if local_std and local_std.value:
            amount = round(float(local_std.value) * persons * days, 2)
            plan.standards_used.append(local_std.code)
            plan.items.append(
                _item(
                    "市内交通",
                    "驻地与赛场间市内交通费",
                    unit="元/人·天",
                    quantity=persons * days,
                    unit_price=float(local_std.value),
                    amount=amount,
                    standard_code=local_std.code,
                    calc_basis=f"{persons} 人 × {days} 天 × {local_std.value} 元/人·天，包干使用",
                    remark="使用学校公务用车的不再补贴",
                )
            )

    def _add_custom_items(self, plan: BudgetPlan, payload: dict[str, Any]) -> None:
        raw_items = payload.get("items") or []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            category = str(raw.get("category") or "其他")
            quantity = float(raw.get("quantity") or 1)
            unit_price = float(raw.get("unit_price") or 0)
            amount = raw.get("amount")
            amount = round(float(amount), 2) if amount is not None else round(quantity * unit_price, 2)
            if amount <= 0:
                continue

            standard = self.find_standard(category, str(payload.get("competition_level") or ""))
            basis = str(raw.get("calc_basis") or "")
            if not basis:
                if standard and standard.value_type == "cap" and unit_price > float(standard.value):
                    basis = f"超出标准 {standard.code} 上限（{standard.value} {standard.unit}）"
                    plan.checks.append(
                        _check(
                            "item_over_standard",
                            "warning",
                            f"{raw.get('item_name') or category} 超出费用标准上限",
                            "请在预算说明中写明必要性，或调整预算金额",
                        )
                    )
                else:
                    basis = "按实际需求估算"
            if standard:
                plan.standards_used.append(standard.code)

            plan.items.append(
                _item(
                    category=category,
                    item_name=str(raw.get("item_name") or category),
                    unit=str(raw.get("unit") or "项"),
                    quantity=quantity,
                    unit_price=unit_price,
                    amount=amount,
                    standard_code=standard.code if standard else "",
                    calc_basis=basis,
                    remark=str(raw.get("remark") or ""),
                )
            )

    # ---------- 校验与汇总 ----------
    def _add_level_checks(self, plan: BudgetPlan, level: str) -> None:
        for rule in self.policy["reimbursement"].get("forbidden_for_levels", []):
            if level in (rule.get("levels") or []):
                hit = [i for i in plan.items if i["category"] in set(rule.get("categories") or [])]
                if hit:
                    plan.checks.append(
                        _check(
                            "level_forbidden_items",
                            "error",
                            f"{rule.get('message')}：{('、'.join(sorted({i['category'] for i in hit})))}",
                            "删除被限制的费用项，或确认该赛事认定级别是否填写正确",
                        )
                    )

        if not plan.summary.get("destination") and any(
            i["category"] in {"交通费", "住宿费"} for i in plan.items
        ):
            plan.checks.append(
                _check(
                    "destination_missing",
                    "warning",
                    "预算包含差旅费用但未填写参赛地点",
                    "补充参赛地点，以便按地区匹配住宿标准",
                )
            )

        if plan.summary.get("mentor_trip") and plan.summary.get("student_count", 0) == 0:
            plan.checks.append(
                _check(
                    "students_missing",
                    "warning",
                    "未填写参赛学生人数",
                    "补充参赛学生名单或人数，报名费与差旅费才能准确计列",
                )
            )

    def _finalize(self, plan: BudgetPlan, payload: dict[str, Any]) -> None:
        plan.total = round(sum(i["amount"] for i in plan.items), 2)
        plan.standards_used = list(dict.fromkeys(plan.standards_used))

        # 指导教师差旅占比提示
        max_share = float(self.policy["budget"].get("max_mentor_share", 0.4))
        mentor_count = plan.summary.get("mentor_count", 0)
        persons = plan.summary.get("trip_persons", 0)
        if persons and mentor_count and plan.summary.get("mentor_trip"):
            share = mentor_count / persons
            if share > max_share:
                plan.checks.append(
                    _check(
                        "mentor_share",
                        "info",
                        f"指导教师占随行人员比例 {share:.0%}，高于常规 {max_share:.0%}",
                        "确认指导教师是否确需随队，必要时压缩随行教师人数",
                    )
                )

        plan.approval = self.approval_route(plan.total)

        if not any(c["level"] == "error" for c in plan.checks):
            plan.checks.insert(
                0,
                _check("budget_ok", "pass", "预算明细与费用标准校验通过", "可直接提交审批"),
            )

        plan.generated_text = self._render_budget_text(plan, payload)

    def approval_route(self, total: float) -> dict[str, Any]:
        ap = self.policy["approval"]
        steps = ["学院（系）负责人审批"]
        if total >= float(ap.get("leader_threshold", 50000)):
            steps = ["学院（系）负责人审批", f"{ap.get('register_office', '教务处')}审核备案", f"{ap.get('leader_role', '分管校领导')}审批"]
            level = "校领导审批"
        elif total >= float(ap.get("register_threshold", 30000)):
            steps = ["学院（系）负责人审批", f"{ap.get('register_office', '教务处')}审核备案"]
            level = "教务处备案"
        elif total < float(ap.get("auto_approve_below", 5000)):
            steps = ["学院（系）负责人审批"]
            level = "学院自行审批"
        else:
            level = "学院审批"
        return {"level": level, "steps": steps, "thresholds": ap}

    def _render_budget_text(self, plan: BudgetPlan, payload: dict[str, Any]) -> str:
        s = plan.summary
        lines = [
            f"关于参加{s.get('competition_name') or '竞赛'}经费预算的申请",
            "",
            f"学院：{payload.get('college') or '计算与智能技术学院'}",
            f"赛事名称：{s.get('competition_name') or '—'}",
            f"赛事级别：{s.get('competition_level') or '—'}",
            f"参赛赛道/赛项：{s.get('track_name') or '—'}",
            f"参赛队伍：{s.get('team_name') or '—'}",
            f"参赛学生：{s.get('student_count')} 人；指导教师：{s.get('mentor_count')} 人"
            f"（{'随队' if s.get('mentor_trip') else '不随队'}）",
            f"参赛地点：{s.get('destination') or '—'}；行程天数：{s.get('trip_days')} 天",
            "",
            "一、预算明细",
        ]
        for i, item in enumerate(plan.items, start=1):
            lines.append(
                f"{i}. {item['item_name']}：{item['quantity']:g} × {item['unit_price']:.2f} 元"
                f"（{item['unit']}） = {item['amount']:.2f} 元"
            )
            if item.get("calc_basis"):
                lines.append(f"   计算依据：{item['calc_basis']}")
        lines += [
            "",
            f"二、预算合计：{plan.total:.2f} 元（大写：{amount_to_chinese(plan.total)}）",
            "",
            "三、审批流程",
            " → ".join(plan.approval["steps"]),
            "",
            "四、说明",
            payload.get("basis")
            or "本次预算依据赛事通知、《学院学科竞赛管理办法》及《差旅费管理办法》编制，"
            "费用标准参照学校现行开支标准执行，实际支出凭合法票据据实报销，结余资金按规定收回。",
        ]
        if payload.get("remark"):
            lines += ["", f"备注：{payload['remark']}"]
        return "\n".join(lines)

    def create_budget(self, payload: dict[str, Any], *, applicant: dict[str, Any] | None = None) -> Budget:
        plan = self.plan_budget(payload)
        applicant = applicant or {}
        budget = Budget(
            doc_no=payload.get("doc_no") or _next_doc_no(self.db, Budget, "YS"),
            title=payload.get("title") or f"{plan.summary['competition_name'] or '竞赛'}经费预算",
            registration_id=payload.get("registration_id"),
            competition_name=plan.summary["competition_name"],
            year=int(payload.get("year") or date.today().year),
            applicant_id=applicant.get("teacher_id"),
            applicant_name=applicant.get("name") or str(payload.get("applicant_name") or ""),
            team_name=plan.summary["team_name"],
            student_count=plan.summary["student_count"],
            teacher_count=plan.summary["mentor_count"],
            destination=plan.summary["destination"],
            trip_days=plan.summary["trip_days"],
            total_amount=plan.total,
            currency=str(payload.get("currency") or "CNY"),
            status=payload.get("status") or "草稿",
            basis=str(payload.get("basis") or ""),
            generated_text=plan.generated_text,
            agent_trace=payload.get("agent_trace") or {},
            remark=str(payload.get("remark") or ""),
        )
        self.db.add(budget)
        self.db.flush()

        for item in plan.items:
            self.db.add(
                BudgetItem(
                    budget_id=budget.id,
                    category=item["category"],
                    item_name=item["item_name"],
                    unit=item["unit"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    amount=item["amount"],
                    standard_code=item["standard_code"],
                    calc_basis=item["calc_basis"],
                    remark=item["remark"],
                )
            )
        self.db.flush()
        return budget

    # ==========================================================
    #  二、借款单
    # ==========================================================
    def plan_loan(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfg = self.policy["loan"]
        borrower = payload.get("borrower") or {}
        name = borrower.get("name") or payload.get("borrower_name") or ""
        teacher_no = borrower.get("teacher_no") or payload.get("borrower_no") or ""
        checks: list[dict[str, Any]] = []

        budget: Budget | None = None
        if payload.get("budget_id"):
            budget = self.db.get(Budget, int(payload["budget_id"]))
        elif payload.get("budget_doc_no") or payload.get("doc_no"):
            doc_no = payload.get("budget_doc_no") or payload.get("doc_no")
            budget = self.db.execute(
                select(Budget).where(Budget.doc_no == str(doc_no))
            ).scalars().first()

        approved_amount: float | None = None
        if budget:
            if cfg.get("require_approved_budget") and budget.status != "已批准":
                checks.append(
                    _check(
                        "budget_not_approved",
                        "error",
                        f"关联预算单 {budget.doc_no} 当前状态为「{budget.status}」，尚未批准",
                        "请先完成预算审批，再办理借款",
                    )
                )
            approved_amount = float(budget.approved_amount or budget.total_amount or 0)
            checks.append(
                _check(
                    "budget_found",
                    "pass",
                    f"已关联预算单 {budget.doc_no}（批准金额 {approved_amount:.2f} 元）",
                    "",
                )
            )
        elif cfg.get("require_approved_budget"):
            checks.append(
                _check(
                    "budget_missing",
                    "error",
                    "未找到已批准的预算单",
                    "借款须以批准的竞赛经费预算为依据，请提供预算单号或先从预算申请流程生成预算",
                )
            )

        amount = payload.get("amount")
        amount = float(amount) if amount is not None else (approved_amount or 0.0)

        if approved_amount is not None and amount > approved_amount:
            checks.append(
                _check(
                    "loan_exceed_budget",
                    "error",
                    f"借款金额 {amount:.2f} 元超过批准预算 {approved_amount:.2f} 元",
                    "借款金额不得超过已批准预算额度",
                )
            )

        limit = float(cfg.get("single_borrow_limit", 20000))
        if amount > limit:
            checks.append(
                _check(
                    "loan_over_limit",
                    "warning",
                    f"借款金额 {amount:.2f} 元超过单笔借款参考上限 {limit:.2f} 元",
                    "大额借款建议按报销计划分批办理，或改由学院先行支付",
                )
            )

        if not name:
            checks.append(
                _check("borrower_missing", "error", "未填写借款人", "借款人须为在编教师，请补充姓名与工号")
            )
        if cfg.get("must_clear_previous") and name:
            try:
                pending = self.db.execute(
                    select(Loan).where(Loan.borrower_name == name, Loan.status == "已借出")
                ).scalars().all()
            except Exception:  # noqa: BLE001
                pending = []
            if pending:
                checks.append(
                    _check(
                        "previous_loan_uncleared",
                        "error",
                        f"借款人存在 {len(pending)} 笔未冲销借款（"
                        + "、".join(l.doc_no for l in pending[:3])
                        + "）",
                        "按「前账未清，不得再借」原则，请先办理已完成借款的冲销",
                    )
                )

        repay_days = int(cfg.get("repay_within_days", 60))
        repay_date = payload.get("expected_repay_date") or (date.today() + timedelta(days=repay_days))
        if isinstance(repay_date, str):
            repay_date = _parse_date(repay_date) or (date.today() + timedelta(days=repay_days))

        content = {
            "单据类型": "借款单（暂付款）",
            "单据编号": payload.get("doc_no") or _next_doc_no(self.db, Loan, "JK", flush=False),
            "借款日期": str(payload.get("loan_date") or date.today()),
            "借款人": name,
            "工号": teacher_no,
            "所在单位": borrower.get("college") or payload.get("college") or "",
            "借款金额（小写）": round(amount, 2),
            "借款金额（大写）": amount_to_chinese(amount),
            "借款用途": payload.get("purpose")
            or (
                f"参加{budget.competition_name}竞赛相关费用支出"
                if budget and budget.competition_name
                else "参加学科竞赛相关费用支出"
            ),
            "预算单号": budget.doc_no if budget else "",
            "赛事名称": budget.competition_name if budget else str(payload.get("competition_name") or ""),
            "参赛地点": (budget.destination if budget else "") or str(payload.get("destination") or ""),
            "收款单位": payload.get("payee") or "按赛事通知指定收款单位",
            "预计还款/冲销日期": str(repay_date),
            "经费来源": payload.get("fund_source") or "学科竞赛专项经费",
            "备注": payload.get("remark") or "",
        }

        if not any(c["level"] == "error" for c in checks):
            checks.insert(0, _check("loan_ok", "pass", "借款单要素与校验通过", "可打印后办理签字手续"))

        return {
            "content": content,
            "amount": round(amount, 2),
            "amount_upper": amount_to_chinese(amount),
            "checks": checks,
            "budget": _budget_brief(budget),
            "generated_text": self._render_loan_text(content, checks),
        }

    def _render_loan_text(self, content: dict[str, Any], checks: list[dict[str, Any]]) -> str:
        lines = ["借 款 单", ""]
        for key, value in content.items():
            if value not in ("", None):
                lines.append(f"{key}：{value}")
        lines += ["", "附：事前校验结果"]
        for c in checks:
            lines.append(f"· [{_level_label(c['level'])}] {c['message']}")
            if c.get("suggestion"):
                lines.append(f"  建议：{c['suggestion']}")
        return "\n".join(lines)

    def create_loan(self, payload: dict[str, Any]) -> Loan:
        plan = self.plan_loan(payload)
        content = plan["content"]
        loan = Loan(
            doc_no=content["单据编号"],
            budget_id=payload.get("budget_id") or (plan["budget"] or {}).get("id"),
            registration_id=payload.get("registration_id"),
            borrower_id=(payload.get("borrower") or {}).get("teacher_id"),
            borrower_name=content["借款人"],
            borrower_no=content["工号"],
            amount=plan["amount"],
            amount_upper=plan["amount_upper"],
            purpose=content["借款用途"],
            competition_name=content["赛事名称"],
            destination=content["参赛地点"],
            expected_repay_date=_parse_date(content["预计还款/冲销日期"]),
            payee=content["收款单位"],
            status=payload.get("status") or "草稿",
            generated_content=content,
            checks=plan["checks"],
            agent_trace=payload.get("agent_trace") or {},
            remark=str(payload.get("remark") or ""),
        )
        self.db.add(loan)
        self.db.flush()
        return loan

    # ==========================================================
    #  三、报销单
    # ==========================================================
    def plan_reimbursement(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfg = self.policy["reimbursement"]
        raw_items = [i for i in (payload.get("items") or []) if isinstance(i, dict)]
        checks: list[dict[str, Any]] = []

        budget: Budget | None = None
        if payload.get("budget_id"):
            budget = self.db.get(Budget, int(payload["budget_id"]))
        elif payload.get("budget_doc_no"):
            budget = self.db.execute(
                select(Budget).where(Budget.doc_no == str(payload["budget_doc_no"]))
            ).scalars().first()

        loan: Loan | None = None
        if payload.get("loan_id"):
            loan = self.db.get(Loan, int(payload["loan_id"]))
        elif payload.get("loan_doc_no"):
            loan = self.db.execute(
                select(Loan).where(Loan.doc_no == str(payload["loan_doc_no"]))
            ).scalars().first()

        level = str(payload.get("competition_level") or "")
        if not level and budget and budget.competition_name:
            comp = self.db.execute(
                select(Competition).where(Competition.name == budget.competition_name)
            ).scalars().first()
            if comp:
                level = comp.level

        # 1) 预算依据
        approved_budget: float | None = None
        if budget:
            approved_budget = float(budget.approved_amount or budget.total_amount or 0)
            if cfg.get("require_budget_approved") and budget.status != "已批准":
                checks.append(
                    _check(
                        "budget_not_approved",
                        "warning",
                        f"关联预算单 {budget.doc_no} 状态为「{budget.status}」",
                        "报销原则上以已批准的预算为前提，请补充审批手续",
                    )
                )
        elif cfg.get("require_budget_approved"):
            checks.append(
                _check(
                    "budget_missing",
                    "warning",
                    "未关联预算单",
                    "请补充关联的预算申请单号，以便核对是否超预算",
                )
            )

        # 2) 逐条明细校验
        item_rows: list[dict[str, Any]] = []
        forbidden_keywords = [str(k) for k in (cfg.get("forbidden_keywords") or [])]
        forbidden_level_rules = cfg.get("forbidden_for_levels") or []
        invoice_above = float(cfg.get("invoice_required_above", 100))

        for raw in raw_items:
            category = str(raw.get("category") or "其他")
            item_name = str(raw.get("item_name") or category)
            amount = round(float(raw.get("amount") or 0), 2)
            has_invoice = bool(raw.get("has_invoice", True))
            invoice_no = str(raw.get("invoice_no") or "")
            expense_date = _parse_date(raw.get("expense_date"))
            remark = str(raw.get("remark") or "")
            payee = str(raw.get("payee") or "")
            over_standard = False
            basis = str(raw.get("calc_basis") or "")

            text_blob = f"{item_name}{remark}{payee}"
            hit_kw = next((k for k in forbidden_keywords if k in text_blob), "")
            if hit_kw:
                checks.append(
                    _check(
                        "forbidden_expense",
                        "error",
                        f"费用项「{item_name}」（{amount:.2f} 元）含不合规支出关键词「{hit_kw}」",
                        "学科竞赛经费不得用于接待、礼品、旅游等与竞赛无关的开支，请删除该项",
                    )
                )

            for rule in forbidden_level_rules:
                if level and level in (rule.get("levels") or []) and category in set(rule.get("categories") or []):
                    checks.append(
                        _check(
                            "level_forbidden_expense",
                            "error",
                            f"「{item_name}」属于{rule.get('message')}（{category}）",
                            "校内比赛不得列支住宿费与差旅类费用",
                        )
                    )

            if cfg.get("invoice_required") and amount > invoice_above and not has_invoice:
                checks.append(
                    _check(
                        "invoice_missing",
                        "error",
                        f"「{item_name}」（{amount:.2f} 元）缺少发票",
                        "单张金额超过 "
                        f"{invoice_above:.0f} 元的支出须凭合法票据报销；如为小额零星支出请补充说明",
                    )
                )
            if has_invoice and amount > invoice_above and not invoice_no:
                checks.append(
                    _check(
                        "invoice_no_missing",
                        "warning",
                        f"「{item_name}」已标记有发票但未填写发票号码",
                        "补充发票号码，便于财务查验",
                    )
                )

            # 与费用标准比对
            standard = self.find_standard(category, level)
            if standard and standard.value_type == "cap" and standard.unit.endswith("天"):
                pass  # 天数类标准需按明细拆分，此处不做单价判断
            elif standard and standard.value and category in {"报名费"} and amount > float(standard.value) * 20:
                over_standard = True

            if expense_date is None:
                checks.append(
                    _check(
                        "expense_date_missing",
                        "warning",
                        f"「{item_name}」缺少费用发生日期",
                        "补充费用发生日期，用于判断是否在竞赛结束后规定期限内报销",
                    )
                )

            item_rows.append(
                {
                    "category": category,
                    "item_name": item_name,
                    "amount": amount,
                    "expense_date": str(expense_date) if expense_date else "",
                    "invoice_no": invoice_no,
                    "has_invoice": has_invoice,
                    "payee": payee,
                    "standard_code": standard.code if standard else "",
                    "over_standard": over_standard,
                    "calc_basis": basis or ("与预算明细一致" if budget else ""),
                    "remark": remark,
                }
            )

        if not item_rows:
            checks.append(_check("items_missing", "error", "未提供报销明细", "请逐项录入实际支出金额与票据情况"))

        total = round(sum(i["amount"] for i in item_rows), 2)

        # 3) 超预算判断
        max_over_ratio = float(cfg.get("max_over_budget_ratio", 0.0))
        if approved_budget is not None and total > approved_budget * (1 + max_over_ratio):
            checks.append(
                _check(
                    "over_budget",
                    "error" if max_over_ratio == 0 else "warning",
                    f"报销总额 {total:.2f} 元超出批准预算 {approved_budget:.2f} 元"
                    f"（超出 {total - approved_budget:.2f} 元）",
                    "超出部分需说明原因并按学院经费管理办法报批，多学院组团参赛的超支部分由各学院均担",
                )
            )

        # 4) 报销时限
        deadline_days = int(cfg.get("deadline_days_after_event", 30))
        event_end = _parse_date(payload.get("event_end_date")) or (
            budget and None
        )
        if event_end:
            latest = event_end + timedelta(days=deadline_days)
            if not payload.get("reimburse_date") or _parse_date(payload.get("reimburse_date")) is None:
                pass
            else:
                rd = _parse_date(payload.get("reimburse_date"))
                if rd and rd > latest:
                    checks.append(
                        _check(
                            "reimbursement_overdue",
                            "warning",
                            f"报销办理日期 {rd} 已超过竞赛结束后 {deadline_days} 天的时限（{latest}）",
                            "逾期报销需在报销单中说明原因，并注意跨年度票据不能入账",
                        )
                    )
        else:
            checks.append(
                _check(
                    "event_date_missing",
                    "info",
                    "未提供竞赛结束日期，无法自动校验报销时限",
                    f"建议补充竞赛结束日期，制度要求在结束后 {deadline_days} 天内办理报销",
                )
            )

        # 5) 材料完整性
        attachments = payload.get("attachments") or {}
        if cfg.get("require_event_notice") and not attachments.get("event_notice", True):
            checks.append(
                _check("event_notice_missing", "error", "缺少参赛通知（会议/竞赛通知）", "作为报销附件之一提交")
            )
        if cfg.get("require_trip_approval") and any(
            i["category"] in TRAVEL_CATEGORIES for i in item_rows
        ) and not attachments.get("trip_approval", True):
            checks.append(
                _check("trip_approval_missing", "error", "差旅支出缺少《因公出差审批表》", "差旅报销须附出差审批表")
            )
        if cfg.get("require_achievement_proof") and payload.get("achieved") and not attachments.get(
            "achievement_proof", True
        ):
            checks.append(
                _check("achievement_proof_missing", "warning", "缺少成绩证明（获奖证书/公示名单）", "作为报销附件提交")
            )
        if not attachments.get("pasted_sheet", True):
            checks.append(
                _check(
                    "pasted_sheet_missing",
                    "warning",
                    "未提供票据粘贴单",
                    "原始票据须按经济内容分类、阶梯状粘贴在票据粘贴专用纸上，并填写金额与附件张数",
                )
            )

        # 6) 冲销借款
        loan_amount = float(loan.amount) if loan else 0.0
        if loan is None:
            checks.append(
                _check(
                    "loan_not_linked",
                    "info",
                    "未关联借款单（如本次未借款可忽略）",
                    "曾办理借款的，报销时须主动告知会计人员冲销暂付款",
                )
            )

        score = _completeness_score(checks)
        if not any(c["level"] == "error" for c in checks):
            checks.insert(0, _check("reimbursement_ok", "pass", "报销明细与附件校验通过", "可提交财务审核"))

        content = {
            "单据类型": "差旅费/竞赛经费报销单",
            "单据编号": payload.get("doc_no") or _next_doc_no(self.db, Reimbursement, "BX", flush=False),
            "报销日期": str(payload.get("reimburse_date") or date.today()),
            "报销人": str(payload.get("claimant_name") or ""),
            "所在单位": str(payload.get("college") or ""),
            "事由": str(payload.get("purpose") or (f"参加{budget.competition_name}竞赛" if budget else "参加学科竞赛")),
            "预算单号": budget.doc_no if budget else "",
            "借款单号": loan.doc_no if loan else "",
            "报销金额（小写）": total,
            "报销金额（大写）": amount_to_chinese(total),
            "冲销借款金额": round(loan_amount, 2),
            "应退/应补金额": round(loan_amount - total, 2) if loan else round(-total, 2),
            "附件张数": int(payload.get("attachment_count") or len(item_rows)),
            "经费来源": str(payload.get("fund_source") or "学科竞赛专项经费"),
        }

        return {
            "items": item_rows,
            "total": total,
            "total_upper": amount_to_chinese(total),
            "checks": checks,
            "completeness_score": score,
            "content": content,
            "budget": _budget_brief(budget),
            "loan": _loan_brief(loan),
            "generated_text": self._render_reimbursement_text(content, item_rows, checks, score),
        }

    def _render_reimbursement_text(
        self,
        content: dict[str, Any],
        items: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        score: float,
    ) -> str:
        lines = ["竞 赛 经 费 报 销 单", ""]
        for key, value in content.items():
            if value not in ("", None):
                lines.append(f"{key}：{value}")
        lines += ["", "一、支出明细"]
        for i, item in enumerate(items, start=1):
            invoice = item["invoice_no"] or ("有发票" if item["has_invoice"] else "无发票")
            lines.append(
                f"{i}. [{item['category']}] {item['item_name']}　{item['amount']:.2f} 元　"
                f"日期：{item['expense_date'] or '—'}　票据：{invoice}"
            )
            if item.get("calc_basis"):
                lines.append(f"   依据：{item['calc_basis']}")
        lines += ["", f"二、合计：{content['报销金额（小写）']:.2f} 元"
                      f"（大写：{content['报销金额（大写）']}）", "", f"三、材料完整性评分：{score:.0f}/100", ""]
        lines.append("四、校验清单")
        for c in checks:
            lines.append(f"· [{_level_label(c['level'])}] {c['message']}")
            if c.get("suggestion"):
                lines.append(f"  建议：{c['suggestion']}")
        return "\n".join(lines)

    def create_reimbursement(self, payload: dict[str, Any]) -> Reimbursement:
        plan = self.plan_reimbursement(payload)
        content = plan["content"]
        budget_id = payload.get("budget_id") or (plan["budget"] or {}).get("id")
        loan_id = payload.get("loan_id") or (plan["loan"] or {}).get("id")
        reimb = Reimbursement(
            doc_no=content["单据编号"],
            budget_id=budget_id,
            loan_id=loan_id,
            registration_id=payload.get("registration_id"),
            competition_name=str(payload.get("competition_name") or (plan["budget"] or {}).get("competition_name") or ""),
            claimant_name=content["报销人"],
            total_amount=plan["total"],
            approved_budget_amount=(plan["budget"] or {}).get("amount"),
            loan_amount=(plan["loan"] or {}).get("amount"),
            status=payload.get("status") or "草稿",
            checks=plan["checks"],
            completeness_score=plan["completeness_score"],
            generated_text=plan["generated_text"],
            agent_trace=payload.get("agent_trace") or {},
            remark=str(payload.get("remark") or ""),
        )
        self.db.add(reimb)
        self.db.flush()

        for item in plan["items"]:
            self.db.add(
                ReimbursementItem(
                    reimbursement_id=reimb.id,
                    category=item["category"],
                    item_name=item["item_name"],
                    amount=item["amount"],
                    expense_date=_parse_date(item["expense_date"]),
                    invoice_no=item["invoice_no"],
                    has_invoice=item["has_invoice"],
                    payee=item["payee"],
                    standard_code=item["standard_code"],
                    over_standard=item["over_standard"],
                    calc_basis=item["calc_basis"],
                    remark=item["remark"],
                )
            )
        self.db.flush()
        return reimb


# ============================================================
#  工具函数
# ============================================================
def _item(
    category: str,
    item_name: str,
    *,
    unit: str = "",
    quantity: float = 1,
    unit_price: float = 0,
    amount: float = 0,
    standard_code: str = "",
    calc_basis: str = "",
    remark: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "item_name": item_name,
        "unit": unit,
        "quantity": round(float(quantity), 2),
        "unit_price": round(float(unit_price), 2),
        "amount": round(float(amount), 2),
        "standard_code": standard_code,
        "calc_basis": calc_basis,
        "remark": remark,
    }


def _check(code: str, level: str, message: str, suggestion: str = "") -> dict[str, str]:
    return {"code": code, "level": level, "message": message, "suggestion": suggestion}


def _level_label(level: str) -> str:
    return {"error": "不合规", "warning": "需注意", "info": "提示", "pass": "通过"}.get(level, level)


def _completeness_score(checks: list[dict[str, Any]]) -> float:
    errors = sum(1 for c in checks if c["level"] == "error")
    warnings = sum(1 for c in checks if c["level"] == "warning")
    score = 100 - errors * 20 - warnings * 6
    return float(max(0, min(100, score)))


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.replace("，", ",").split(",") if v.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            if isinstance(v, dict):
                out.append(str(v.get("name") or v.get("student_name") or "").strip())
            else:
                out.append(str(v).strip())
        return [v for v in out if v]
    return []


def _region_of(destination: str) -> str:
    if not destination:
        return "不限"
    for city in ("北京", "上海", "广州", "深圳"):
        if city in destination:
            return city
    for region in ("西藏", "青海", "新疆"):
        if region in destination:
            return region
    return "不限"


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        from datetime import datetime

        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _days_between(start: Any, end: Any) -> int:
    s, e = _parse_date(start), _parse_date(end)
    if not s or not e:
        return 0
    return (e - s).days + 1


def _next_doc_no(db: Session, model, prefix: str, *, flush: bool = True) -> str:
    from sqlalchemy import func

    year = date.today().year
    count = db.execute(select(func.count(model.id))).scalar() or 0
    seq = int(count) + 1
    candidate = f"{prefix}{year}{seq:04d}"
    # 极小概率的并发重号，向后顺延保证唯一
    for _ in range(50):
        exists = db.execute(select(model.id).where(model.doc_no == candidate)).first()
        if not exists:
            return candidate
        seq += 1
        candidate = f"{prefix}{year}{seq:04d}"
    return f"{prefix}{year}{seq:04d}"


def _budget_brief(budget: Budget | None) -> dict[str, Any] | None:
    if not budget:
        return None
    return {
        "id": budget.id,
        "doc_no": budget.doc_no,
        "title": budget.title,
        "competition_name": budget.competition_name,
        "status": budget.status,
        "amount": float(budget.approved_amount or budget.total_amount or 0),
        "total_amount": float(budget.total_amount or 0),
        "approved_amount": float(budget.approved_amount) if budget.approved_amount is not None else None,
        "destination": budget.destination,
        "trip_days": budget.trip_days,
        "applicant_name": budget.applicant_name,
    }


def _loan_brief(loan: Loan | None) -> dict[str, Any] | None:
    if not loan:
        return None
    return {
        "id": loan.id,
        "doc_no": loan.doc_no,
        "amount": float(loan.amount or 0),
        "status": loan.status,
        "borrower_name": loan.borrower_name,
        "purpose": loan.purpose,
        "expected_repay_date": str(loan.expected_repay_date) if loan.expected_repay_date else "",
    }


def summarize_policy() -> dict[str, Any]:
    """把当前生效的规则参数整理成可读文本，供智能体在回答中引用依据。"""
    p = finance_policy()
    ap = p["approval"]
    rb = p["reimbursement"]
    ln = p["loan"]
    return {
        "审批阈值": {
            "学院自行审批": f"低于 {ap.get('auto_approve_below')} 元",
            "教务处备案": f"达到 {ap.get('register_threshold')} 元",
            "校领导审批": f"达到 {ap.get('leader_threshold')} 元",
        },
        "报销要求": {
            "报销时限": f"竞赛结束后 {rb.get('deadline_days_after_event')} 天内办理",
            "发票要求": f"单张超过 {rb.get('invoice_required_above')} 元须提供合法票据",
            "超预算": "不允许超支" if float(rb.get("max_over_budget_ratio", 0)) == 0 else f"允许超出 {rb.get('max_over_budget_ratio')}",
            "禁止事项": "、".join(rb.get("forbidden_keywords") or []),
        },
        "借款要求": {
            "前提": "须以已批准的预算为依据" if ln.get("require_approved_budget") else "无",
            "单笔上限": f"{ln.get('single_borrow_limit')} 元",
            "前账未清不得再借": bool(ln.get("must_clear_previous")),
            "冲销期限": f"{ln.get('repay_within_days')} 天",
        },
        "规则出处": "data/rules/finance_policy.yaml",
    }


def truncate_text(text: str, limit: int = 200) -> str:
    return truncate(text, limit)