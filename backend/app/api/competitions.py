"""赛事台账与规则查询接口。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..db.models import (
    AwardPointRule,
    AwardSetting,
    Competition,
    CompetitionCategoryRule,
    CompetitionEdition,
    CompetitionTrack,
    EditionMilestone,
    ExpenseStandard,
    Registration,
    RegistrationMember,
    RegistrationMentor,
)
from ..services.competition_service import CompetitionService
from ..security import require

router = APIRouter()


class CompetitionIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    short_name: str = ""
    organizer: str = ""
    co_organizer: str = ""
    level: str = "国家级"
    category: str = ""
    competition_type: str = ""
    discipline_tags: list[str] = Field(default_factory=list)
    official_url: str = ""
    intro: str = ""
    target_audience: str = ""
    is_active: bool = True


class MilestoneIn(BaseModel):
    name: str
    stage: str = ""
    start_date: str = ""
    end_date: str = ""
    note: str = ""


class TrackIn(BaseModel):
    name: str
    code: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    team_size_min: int | None = None
    team_size_max: int | None = None
    fee: float | None = None
    discipline_tags: list[str] = Field(default_factory=list)


class AwardSettingIn(BaseModel):
    award_level: str
    category: str = ""
    ratio: str = ""
    quantity: str = ""
    prize: str = ""
    note: str = ""


class EditionIn(BaseModel):
    year: int
    edition_name: str = ""
    notice_title: str = ""
    notice_no: str = ""
    issued_by: str = ""
    issued_date: str = ""
    register_start: str = ""
    register_end: str = ""
    competition_period: str = ""
    eligibility: str = ""
    team_size_min: int = 1
    team_size_max: int = 1
    mentor_limit: int = 1
    registration_fee: float = 0
    fee_note: str = ""
    required_materials: list[Any] = Field(default_factory=list)
    material_note: str = ""
    status: str = "筹备中"
    source_ref: str = ""
    milestones: list[MilestoneIn] = Field(default_factory=list)
    tracks: list[TrackIn] = Field(default_factory=list)
    award_settings: list[AwardSettingIn] = Field(default_factory=list)


def _d(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise HTTPException(400, f"日期格式应为 YYYY-MM-DD：{value}") from exc


@router.get("/competitions", dependencies=[Depends(require("competitions.read"))])
def list_competitions(
    keyword: str = "", level: str = "", active_only: bool = True, db: Session = Depends(get_db)
) -> dict[str, Any]:
    svc = CompetitionService(db)
    items = svc.list_competitions(keyword=keyword, level=level, active_only=active_only)
    return {"items": items, "total": len(items)}


@router.get("/competitions/upcoming", dependencies=[Depends(require("competitions.read"))])
def upcoming(days: int = 180, db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": CompetitionService(db).upcoming_milestones(days=min(max(days, 1), 730))}


@router.get("/competitions/{competition_id}", dependencies=[Depends(require("competitions.read"))])
def competition_detail(competition_id: int, year: int | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    data = CompetitionService(db).detail(competition_id, year)
    if not data:
        raise HTTPException(404, "赛事不存在")
    return data


@router.post("/competitions", dependencies=[Depends(require("competitions.write"))])
def create_competition(body: CompetitionIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    exists = db.execute(select(Competition).where(Competition.code == body.code)).scalars().first()
    if exists:
        raise HTTPException(409, f"赛事编码 {body.code} 已存在")
    comp = Competition(**body.model_dump())
    db.add(comp)
    db.commit()
    return {"id": comp.id, "name": comp.name}


@router.put("/competitions/{competition_id}", dependencies=[Depends(require("competitions.write"))])
def update_competition(competition_id: int, body: CompetitionIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(404, "赛事不存在")
    dup = db.execute(
        select(Competition).where(Competition.code == body.code, Competition.id != competition_id)
    ).scalars().first()
    if dup:
        raise HTTPException(409, f"赛事编码 {body.code} 已被占用")
    for key, value in body.model_dump().items():
        setattr(comp, key, value)
    db.commit()
    return {"id": comp.id, "name": comp.name}


@router.post("/competitions/{competition_id}/editions", dependencies=[Depends(require("competitions.write"))])
def upsert_edition(competition_id: int, body: EditionIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(404, "赛事不存在")
    edition = db.execute(
        select(CompetitionEdition).where(
            CompetitionEdition.competition_id == competition_id,
            CompetitionEdition.year == body.year,
            CompetitionEdition.edition_name == body.edition_name,
        )
    ).scalars().first()
    created = edition is None
    if edition is None:
        edition = CompetitionEdition(competition_id=competition_id, year=body.year, edition_name=body.edition_name)
        db.add(edition)
        db.flush()

    fields = body.model_dump(exclude={"milestones", "tracks", "award_settings"})
    for key, value in fields.items():
        if key.endswith("_date") or key in {"register_start", "register_end"}:
            value = _d(value)
        setattr(edition, key, value)

    for collection in (edition.milestones, edition.tracks):
        for row in list(collection):
            db.delete(row)
    for row in list(edition.award_rules):
        db.delete(row)
    db.flush()

    for m in body.milestones:
        db.add(EditionMilestone(
            edition_id=edition.id, name=m.name, stage=m.stage,
            start_date=_d(m.start_date), end_date=_d(m.end_date), note=m.note,
        ))
    for t in body.tracks:
        db.add(CompetitionTrack(edition_id=edition.id, **t.model_dump()))
    for a in body.award_settings:
        db.add(AwardSetting(edition_id=edition.id, **a.model_dump()))
    db.commit()
    return {"id": edition.id, "created": created, "year": edition.year, "edition_name": edition.edition_name}


@router.delete("/competitions/{competition_id}", dependencies=[Depends(require("competitions.write"))])
def delete_competition(competition_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(404, "赛事不存在")
    used = db.execute(select(Registration.id).where(Registration.competition_id == competition_id).limit(1)).first()
    if used:
        comp.is_active = False
        db.commit()
        return {"ok": True, "archived": True, "message": "赛事已有台账记录，已设为停用而非删除"}
    db.delete(comp)
    db.commit()
    return {"ok": True, "archived": False}


@router.get("/ledger/registrations", dependencies=[Depends(require("ledger.read"))])
def ledger_registrations(
    db: Session = Depends(get_db),
    year: int | None = None,
    competition: str = "",
    level: str = "",
    status: str = "",
    major: str = "",
    teacher: str = "",
    student: str = "",
    keyword: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    stmt = select(Registration)
    if year:
        stmt = stmt.where(Registration.year == year)
    if competition:
        stmt = stmt.where(Registration.competition_name == competition)
    if level:
        stmt = stmt.where(Registration.competition_level == level)
    if status:
        stmt = stmt.where(Registration.status == status)
    if major:
        stmt = stmt.where(or_(
            Registration.lead_major.like(f"%{major}%"),
            Registration.members.any(RegistrationMember.major_name.like(f"%{major}%")),
        ))
    if teacher:
        stmt = stmt.where(Registration.mentors.any(RegistrationMentor.teacher_name.like(f"%{teacher}%")))
    if student:
        stmt = stmt.where(Registration.members.any(RegistrationMember.student_name.like(f"%{student}%")))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(
            Registration.competition_name.like(kw),
            Registration.track_name.like(kw),
            Registration.team_name.like(kw),
            Registration.project_title.like(kw),
            Registration.leader_name.like(kw),
            Registration.mentor_names.like(kw),
        ))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0)
    rows = db.execute(stmt.order_by(desc(Registration.year), desc(Registration.id))
                      .offset(max(offset, 0)).limit(min(max(limit, 1), 200))).scalars().all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": r.id, "code": r.code, "year": r.year,
                "competition_name": r.competition_name, "track_name": r.track_name,
                "competition_level": r.competition_level, "competition_category": r.competition_category,
                "team_name": r.team_name, "project_title": r.project_title,
                "status": r.status, "stage_reached": r.stage_reached,
                "register_date": str(r.register_date) if r.register_date else "",
                "finish_date": str(r.finish_date) if r.finish_date else "",
                "lead_major": r.lead_major, "leader_name": r.leader_name,
                "mentor_names": r.mentor_names,
                "members": [
                    {"student_no": m.student_no, "student_name": m.student_name,
                     "major_name": m.major_name, "grade": m.grade, "role": m.role}
                    for m in sorted(r.members, key=lambda x: x.order_no)
                ],
                "mentors": [
                    {"teacher_name": m.teacher_name, "role": m.role}
                    for m in sorted(r.mentors, key=lambda x: x.order_no)
                ],
                "awards": [
                    {"award_year": a.award_year, "award_level": a.award_level,
                     "award_grade": a.award_grade, "project_title": a.project_title,
                     "students": a.students, "mentors": a.mentors, "points": a.points,
                     "certificate_no": a.certificate_no,
                     "award_date": str(a.award_date) if a.award_date else ""}
                    for a in r.awards
                ],
            }
            for r in rows
        ],
    }


@router.get("/rules", dependencies=[Depends(require("competitions.read"))])
def rule_tables(db: Session = Depends(get_db)) -> dict[str, Any]:
    standards = db.execute(select(ExpenseStandard).order_by(ExpenseStandard.category, ExpenseStandard.code)).scalars().all()
    awards = db.execute(
        select(AwardPointRule).order_by(AwardPointRule.award_grade, AwardPointRule.award_level)
    ).scalars().all()
    categories = db.execute(
        select(CompetitionCategoryRule).order_by(CompetitionCategoryRule.level, CompetitionCategoryRule.competition_name_pattern)
    ).scalars().all()
    return {
        "expense_standards": [
            {
                "code": s.code, "name": s.name, "category": s.category,
                "competition_level": s.competition_level, "region": s.region,
                "value_type": s.value_type, "value": s.value, "unit": s.unit,
                "description": s.description, "source": s.source,
                "effective_from": str(s.effective_from) if s.effective_from else "",
                "effective_to": str(s.effective_to) if s.effective_to else "",
            }
            for s in standards
        ],
        "award_point_rules": [
            {
                "award_grade": a.award_grade,
                "award_level": a.award_level,
                "student_points": a.student_points,
                "teacher_workload": a.teacher_workload,
                "note": a.note,
                "source": a.source,
            }
            for a in awards
        ],
        "competition_category_rules": [
            {
                "competition_name_pattern": c.competition_name_pattern,
                "category": c.category,
                "level": c.level,
                "score": c.score,
                "note": c.note,
                "source": c.source,
            }
            for c in categories
        ],
        "sources": {
            "expense": "data/rules/expense_standards.yaml",
            "award_points": "data/rules/award_point_rules.yaml",
            "categories": "data/rules/competition_category_rules.yaml",
            "recommendation": "data/rules/recommend_weights.yaml",
            "review": "data/rules/review_rubrics.yaml",
        },
    }
