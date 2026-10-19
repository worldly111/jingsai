"""预算、借款、报销接口与单据导出。"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..db.models import Budget, BudgetItem, Loan, Reimbursement, ReimbursementItem
from ..services.export_service import (
    ExportService,
    list_budgets,
    list_loans,
    list_reimbursements,
)
from ..services.finance_service import FinanceService
from ..security import current_role, require

router = APIRouter(dependencies=[Depends(require("finance.use"))])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SUBMIT_STATUSES = {"草稿", "待审批", "待审核"}


def _ensure_status_allowed(status: str, role: str) -> None:
    if role != "管理员" and status not in _SUBMIT_STATUSES:
        raise HTTPException(403, "当前身份（教师）只能保存草稿或提交审批，批准、驳回与资金办理须由管理员操作")


class PlanRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class BudgetCreate(PlanRequest):
    applicant: dict[str, Any] = Field(default_factory=dict)
    status: str = "草稿"
    doc_no: str = ""
    title: str = ""
    agent_trace: dict[str, Any] = Field(default_factory=dict)


class LoanCreate(PlanRequest):
    agent_trace: dict[str, Any] = Field(default_factory=dict)
    status: str = "草稿"


class ReimbursementCreate(PlanRequest):
    agent_trace: dict[str, Any] = Field(default_factory=dict)
    status: str = "草稿"


class StatusUpdate(BaseModel):
    status: str
    approved_amount: float | None = None
    reviewer: str = ""
    note: str = ""


def _download(name: str, data: bytes, media: str) -> Response:
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    })


def _budget_detail(db: Session, budget: Budget) -> dict[str, Any]:
    return {
        "id": budget.id, "doc_no": budget.doc_no, "title": budget.title,
        "competition_name": budget.competition_name, "year": budget.year,
        "applicant_name": budget.applicant_name, "team_name": budget.team_name,
        "student_count": budget.student_count, "teacher_count": budget.teacher_count,
        "destination": budget.destination, "trip_days": budget.trip_days,
        "total_amount": float(budget.total_amount or 0),
        "approved_amount": float(budget.approved_amount) if budget.approved_amount is not None else None,
        "status": budget.status, "basis": budget.basis,
        "reviewer": budget.reviewer, "review_note": budget.review_note,
        "review_date": str(budget.review_date) if budget.review_date else "",
        "generated_text": budget.generated_text, "remark": budget.remark,
        "created_at": budget.created_at.isoformat() if budget.created_at else "",
        "items": [
            {
                "id": i.id, "category": i.category, "item_name": i.item_name,
                "unit": i.unit, "quantity": i.quantity, "unit_price": i.unit_price,
                "amount": float(i.amount or 0), "standard_code": i.standard_code,
                "calc_basis": i.calc_basis, "remark": i.remark,
            }
            for i in budget.items
        ],
    }


def _loan_detail(loan: Loan) -> dict[str, Any]:
    return {
        "id": loan.id, "doc_no": loan.doc_no, "borrower_name": loan.borrower_name,
        "borrower_no": loan.borrower_no, "amount": float(loan.amount or 0),
        "amount_upper": loan.amount_upper, "purpose": loan.purpose,
        "competition_name": loan.competition_name, "destination": loan.destination,
        "budget_id": loan.budget_id,
        "expected_repay_date": str(loan.expected_repay_date) if loan.expected_repay_date else "",
        "payee": loan.payee, "status": loan.status,
        "checks": loan.checks, "generated_content": loan.generated_content,
        "created_at": loan.created_at.isoformat() if loan.created_at else "",
    }


def _reimb_detail(reimb: Reimbursement) -> dict[str, Any]:
    return {
        "id": reimb.id, "doc_no": reimb.doc_no, "claimant_name": reimb.claimant_name,
        "competition_name": reimb.competition_name, "total_amount": float(reimb.total_amount or 0),
        "approved_budget_amount": float(reimb.approved_budget_amount) if reimb.approved_budget_amount is not None else None,
        "loan_amount": float(reimb.loan_amount) if reimb.loan_amount is not None else None,
        "status": reimb.status, "completeness_score": reimb.completeness_score,
        "checks": reimb.checks, "generated_text": reimb.generated_text,
        "created_at": reimb.created_at.isoformat() if reimb.created_at else "",
        "items": [
            {
                "id": i.id, "category": i.category, "item_name": i.item_name,
                "amount": float(i.amount or 0),
                "expense_date": str(i.expense_date) if i.expense_date else "",
                "invoice_no": i.invoice_no, "has_invoice": i.has_invoice,
                "payee": i.payee, "over_standard": i.over_standard,
                "calc_basis": i.calc_basis, "remark": i.remark,
            }
            for i in reimb.items
        ],
    }


# ============================================================
#  预算
# ============================================================
@router.post("/finance/budgets/plan")
def plan_budget(body: PlanRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return FinanceService(db).plan_budget(body.payload).to_dict()


@router.post("/finance/budgets")
def create_budget(
    body: BudgetCreate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    _ensure_status_allowed(body.status, role)
    payload = dict(body.payload)
    if body.doc_no:
        payload["doc_no"] = body.doc_no
    if body.title:
        payload["title"] = body.title
    payload["status"] = body.status
    payload["agent_trace"] = body.agent_trace
    budget = FinanceService(db).create_budget(payload, applicant=body.applicant)
    db.commit()
    return _budget_detail(db, budget)


@router.get("/finance/budgets")
def budgets(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": list_budgets(db)}


@router.get("/finance/budgets/{budget_id}")
def budget_detail(budget_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(404, "预算单不存在")
    return _budget_detail(db, budget)


@router.patch("/finance/budgets/{budget_id}/status")
def budget_status(
    budget_id: int, body: StatusUpdate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(404, "预算单不存在")
    if body.status not in {"草稿", "待审批", "已批准", "已驳回"}:
        raise HTTPException(400, "状态应为 草稿/待审批/已批准/已驳回")
    _ensure_status_allowed(body.status, role)
    budget.status = body.status
    budget.reviewer = body.reviewer
    budget.review_note = body.note
    budget.review_date = date.today()
    if body.status == "已批准":
        budget.approved_amount = body.approved_amount if body.approved_amount is not None else budget.total_amount
    db.commit()
    return _budget_detail(db, budget)


@router.get("/finance/budgets/{budget_id}/doc")
def budget_doc(budget_id: int, format: str = "docx", db: Session = Depends(get_db)) -> Response:
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(404, "预算单不存在")
    name, data, ext = ExportService(db).budget_doc(budget, as_word=format != "xlsx")
    return _download(name, data, DOCX if ext == "docx" else XLSX)


# ============================================================
#  借款
# ============================================================
@router.post("/finance/loans/plan")
def plan_loan(body: PlanRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return FinanceService(db).plan_loan(body.payload)


@router.post("/finance/loans")
def create_loan(
    body: LoanCreate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    _ensure_status_allowed(body.status, role)
    payload = dict(body.payload)
    payload["status"] = body.status
    payload["agent_trace"] = body.agent_trace
    loan = FinanceService(db).create_loan(payload)
    db.commit()
    return _loan_detail(loan)


@router.get("/finance/loans")
def loans(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": list_loans(db)}


@router.get("/finance/loans/{loan_id}")
def loan_detail(loan_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    loan = db.get(Loan, loan_id)
    if not loan:
        raise HTTPException(404, "借款单不存在")
    return _loan_detail(loan)


@router.patch("/finance/loans/{loan_id}/status")
def loan_status(
    loan_id: int, body: StatusUpdate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    loan = db.get(Loan, loan_id)
    if not loan:
        raise HTTPException(404, "借款单不存在")
    _ensure_status_allowed(body.status, role)
    loan.status = body.status
    db.commit()
    return _loan_detail(loan)


@router.get("/finance/loans/{loan_id}/doc")
def loan_doc(loan_id: int, format: str = "docx", db: Session = Depends(get_db)) -> Response:
    loan = db.get(Loan, loan_id)
    if not loan:
        raise HTTPException(404, "借款单不存在")
    name, data, ext = ExportService(db).loan_doc(loan, as_word=format != "xlsx")
    return _download(name, data, DOCX if ext == "docx" else XLSX)


# ============================================================
#  报销
# ============================================================
@router.post("/finance/reimbursements/plan")
def plan_reimbursement(body: PlanRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return FinanceService(db).plan_reimbursement(body.payload)


@router.post("/finance/reimbursements")
def create_reimbursement(
    body: ReimbursementCreate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    _ensure_status_allowed(body.status, role)
    payload = dict(body.payload)
    payload["status"] = body.status
    payload["agent_trace"] = body.agent_trace
    reimb = FinanceService(db).create_reimbursement(payload)
    db.commit()
    return _reimb_detail(reimb)


@router.get("/finance/reimbursements")
def reimbursements(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": list_reimbursements(db)}


@router.get("/finance/reimbursements/{reimb_id}")
def reimbursement_detail(reimb_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    reimb = db.get(Reimbursement, reimb_id)
    if not reimb:
        raise HTTPException(404, "报销单不存在")
    return _reimb_detail(reimb)


@router.patch("/finance/reimbursements/{reimb_id}/status")
def reimbursement_status(
    reimb_id: int, body: StatusUpdate, db: Session = Depends(get_db),
    role: str = Depends(current_role),
) -> dict[str, Any]:
    reimb = db.get(Reimbursement, reimb_id)
    if not reimb:
        raise HTTPException(404, "报销单不存在")
    if body.status not in {"草稿", "待审核", "已通过", "已驳回"}:
        raise HTTPException(400, "状态应为 草稿/待审核/已通过/已驳回")
    _ensure_status_allowed(body.status, role)
    reimb.status = body.status
    result = _reimb_detail(reimb)
    if body.status == "已通过" and reimb.loan_id:
        loan = db.get(Loan, reimb.loan_id)
        if loan and loan.status != "已冲销":
            loan.status = "已冲销"
            result["closed_loan_doc_no"] = loan.doc_no
    db.commit()
    return result


@router.get("/finance/reimbursements/{reimb_id}/doc")
def reimbursement_doc(reimb_id: int, format: str = "docx", db: Session = Depends(get_db)) -> Response:
    reimb = db.get(Reimbursement, reimb_id)
    if not reimb:
        raise HTTPException(404, "报销单不存在")
    name, data, ext = ExportService(db).reimbursement_doc(reimb, as_word=format != "xlsx")
    return _download(name, data, DOCX if ext == "docx" else XLSX)


# ============================================================
#  财务概览
# ============================================================
@router.get("/finance/summary")
def finance_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    budget_total = float(db.execute(select(func.coalesce(func.sum(Budget.total_amount), 0))).scalar() or 0)
    approved_total = float(db.execute(select(func.coalesce(func.sum(Budget.approved_amount), 0))).scalar() or 0)
    loan_total = float(db.execute(select(func.coalesce(func.sum(Loan.amount), 0))).scalar() or 0)
    reimb_total = float(db.execute(select(func.coalesce(func.sum(Reimbursement.total_amount), 0))).scalar() or 0)
    return {
        "budgets": int(db.query(Budget).count()),
        "budgets_pending": int(db.query(Budget).filter(Budget.status == "待审批").count()),
        "budget_total": budget_total,
        "approved_total": approved_total,
        "loans": int(db.query(Loan).count()),
        "loan_total": loan_total,
        "reimbursements": int(db.query(Reimbursement).count()),
        "reimbursement_total": reimb_total,
        "recent_budgets": list_budgets(db, limit=5),
        "recent_loans": list_loans(db, limit=5),
        "recent_reimbursements": list_reimbursements(db, limit=5),
    }
