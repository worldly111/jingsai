"""导入学院主数据、竞赛目录、规则与竞赛台账。

所有数据来自 data/seed 与 data/rules 目录，可重复执行（按业务主键 upsert）。
新增赛事 / 年度数据时，只需补充 JSON 后重新运行本脚本，无需修改代码。

用法：
    python scripts/seed_data.py                 # 全量导入
    python scripts/seed_data.py --skip-ledger   # 只导入主数据、赛事与规则
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.db.models import (  # noqa: E402
    Award,
    AwardPointRule,
    AwardSetting,
    Competition,
    CompetitionCategoryRule,
    CompetitionEdition,
    CompetitionTrack,
    EditionMilestone,
    ExpenseStandard,
    Major,
    MajorCompetitionFit,
    Registration,
    RegistrationMember,
    RegistrationMentor,
    Student,
    Teacher,
)
from app.services import policy  # noqa: E402

SEED_DIR = settings.seed_path
RULES_DIR = settings.rules_path


def _load(name: str) -> dict[str, Any]:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# ============================================================
#  一、主数据：专业 / 学生 / 教师
# ============================================================
def seed_master(db) -> dict[str, int]:
    data = _load("master.json")
    college = str(data.get("college") or settings.default_college)

    major_by_code: dict[str, Major] = {}
    for item in data.get("majors", []):
        obj = db.execute(select(Major).where(Major.code == item["code"])).scalars().first()
        if obj is None:
            obj = Major(code=item["code"])
            db.add(obj)
        obj.name = item["name"]
        obj.college = college
        obj.discipline = item.get("discipline", "")
        obj.description = item.get("description", "")
        major_by_code[item["code"]] = obj
    db.flush()

    for item in data.get("teachers", []):
        obj = db.execute(select(Teacher).where(Teacher.teacher_no == item["teacher_no"])).scalars().first()
        if obj is None:
            obj = Teacher(teacher_no=item["teacher_no"])
            db.add(obj)
        obj.name = item["name"]
        obj.title = item.get("title", "")
        obj.college = college
        obj.department = item.get("department", "")
        obj.research_areas = item.get("research_areas", [])
        obj.phone = item.get("phone", "")
        obj.email = item.get("email", "")
        obj.can_mentor = True

    for item in data.get("students", []):
        obj = db.execute(select(Student).where(Student.student_no == item["student_no"])).scalars().first()
        if obj is None:
            obj = Student(student_no=item["student_no"])
            db.add(obj)
        major = major_by_code.get(item.get("major_code", ""))
        obj.name = item["name"]
        obj.gender = item.get("gender", "")
        obj.major_id = major.id if major else None
        obj.major_name = major.name if major else ""
        obj.grade = item.get("grade", "")
        obj.class_name = item.get("class_name", "")
        obj.tech_tags = item.get("tech_tags", [])
        obj.skill_level = item.get("skill_level", "")

    db.flush()
    return {
        "majors": len(data.get("majors", [])),
        "teachers": len(data.get("teachers", [])),
        "students": len(data.get("students", [])),
    }


# ============================================================
#  二、赛事目录：赛事 / 届次 / 赛道 / 时间节点 / 奖项 / 适配矩阵
# ============================================================
def seed_competitions(db) -> dict[str, int]:
    data = _load("competitions.json")
    n_comp = n_edition = n_track = n_fit = 0

    for item in data.get("competitions", []):
        comp = db.execute(select(Competition).where(Competition.code == item["code"])).scalars().first()
        if comp is None:
            comp = Competition(code=item["code"])
            db.add(comp)
        comp.name = item["name"]
        comp.short_name = item.get("short_name", "")
        comp.organizer = item.get("organizer", "")
        comp.co_organizer = item.get("co_organizer", "")
        comp.level = item.get("level", "国家级")
        comp.category = item.get("category", "")
        comp.competition_type = item.get("competition_type", "")
        comp.discipline_tags = item.get("discipline_tags", [])
        comp.official_url = item.get("official_url", "")
        comp.intro = item.get("intro", "")
        comp.target_audience = item.get("target_audience", "")
        comp.is_active = True
        db.flush()
        n_comp += 1

        for ed_item in item.get("editions", []):
            edition = db.execute(
                select(CompetitionEdition).where(
                    CompetitionEdition.competition_id == comp.id,
                    CompetitionEdition.year == ed_item["year"],
                    CompetitionEdition.edition_name == ed_item.get("edition_name", ""),
                )
            ).scalars().first()
            if edition is None:
                edition = CompetitionEdition(
                    competition_id=comp.id,
                    year=ed_item["year"],
                    edition_name=ed_item.get("edition_name", ""),
                )
                db.add(edition)
            edition.notice_title = ed_item.get("notice_title", "")
            edition.notice_no = ed_item.get("notice_no", "")
            edition.issued_by = ed_item.get("issued_by", "")
            edition.issued_date = _date(ed_item.get("issued_date"))
            edition.register_start = _date(ed_item.get("register_start"))
            edition.register_end = _date(ed_item.get("register_end"))
            edition.competition_period = ed_item.get("competition_period", "")
            edition.eligibility = ed_item.get("eligibility", "")
            edition.team_size_min = int(ed_item.get("team_size_min") or 1)
            edition.team_size_max = int(ed_item.get("team_size_max") or 1)
            edition.mentor_limit = int(ed_item.get("mentor_limit") or 0)
            edition.registration_fee = float(ed_item.get("registration_fee") or 0)
            edition.fee_note = ed_item.get("fee_note", "")
            edition.required_materials = ed_item.get("required_materials", [])
            edition.material_note = ed_item.get("material_note", "")
            edition.status = ed_item.get("status", "往届")
            edition.source_ref = ed_item.get("source_ref", "")
            db.flush()
            n_edition += 1

            for track_item in ed_item.get("tracks", []):
                track = db.execute(
                    select(CompetitionTrack).where(
                        CompetitionTrack.edition_id == edition.id,
                        CompetitionTrack.name == track_item["name"],
                    )
                ).scalars().first()
                if track is None:
                    track = CompetitionTrack(edition_id=edition.id, name=track_item["name"])
                    db.add(track)
                track.code = track_item.get("code", "")
                track.description = track_item.get("description", "")
                track.requirements = track_item.get("requirements", [])
                track.team_size_min = track_item.get("team_size_min")
                track.team_size_max = track_item.get("team_size_max")
                track.fee = track_item.get("fee")
                track.discipline_tags = track_item.get("discipline_tags", [])
                n_track += 1

            db.execute(delete(EditionMilestone).where(EditionMilestone.edition_id == edition.id))
            for ms in ed_item.get("milestones", []):
                db.add(
                    EditionMilestone(
                        edition_id=edition.id,
                        name=ms.get("name", ""),
                        stage=ms.get("stage", ""),
                        start_date=_date(ms.get("start_date")),
                        end_date=_date(ms.get("end_date")),
                        note=ms.get("note", ""),
                    )
                )

            db.execute(delete(AwardSetting).where(AwardSetting.edition_id == edition.id))
            for aw in ed_item.get("award_settings", []):
                db.add(
                    AwardSetting(
                        edition_id=edition.id,
                        award_level=aw.get("award_level", ""),
                        ratio=aw.get("ratio", ""),
                        quantity=aw.get("quantity", ""),
                        category=aw.get("category", ""),
                        prize=aw.get("prize", ""),
                        note=aw.get("note", ""),
                    )
                )

        db.execute(delete(MajorCompetitionFit).where(MajorCompetitionFit.competition_id == comp.id))
        for fit in item.get("fits", []):
            db.add(
                MajorCompetitionFit(
                    competition_id=comp.id,
                    match_type=fit.get("match_type", "major"),
                    match_value=fit.get("match_value", ""),
                    fit_score=float(fit.get("fit_score") or 0.8),
                    reason=fit.get("reason", ""),
                    recommended_grade=fit.get("recommended_grade", ""),
                    difficulty=fit.get("difficulty", "中"),
                )
            )
            n_fit += 1
        db.flush()

    return {"competitions": n_comp, "editions": n_edition, "tracks": n_track, "fits": n_fit}


# ============================================================
#  三、规则：费用标准 / 获奖积分 / 认定目录
# ============================================================
def seed_rules(db) -> dict[str, int]:
    db.execute(delete(ExpenseStandard))
    for item in policy.expense_standards_seed():
        db.add(
            ExpenseStandard(
                code=item["code"],
                name=item.get("name", ""),
                category=item.get("category", ""),
                competition_level=item.get("competition_level", "不限"),
                region=item.get("region", "不限"),
                value_type=item.get("value_type", "cap"),
                value=float(item.get("value") or 0),
                unit=item.get("unit", ""),
                condition=item.get("condition") or {},
                description=item.get("description", ""),
                source=item.get("source") or "data/rules/expense_standards.yaml",
                effective_from=_date(item.get("effective_from")),
                effective_to=_date(item.get("effective_to")),
                is_active=True,
            )
        )

    db.execute(delete(AwardPointRule))
    for item in policy.award_point_rules_seed():
        db.add(
            AwardPointRule(
                award_grade=item.get("award_grade", ""),
                award_level=item.get("award_level", ""),
                student_points=float(item.get("student_points") or 0),
                teacher_workload=float(item.get("teacher_workload") or 0),
                note=item.get("note", ""),
                source=item.get("source") or "data/rules/award_point_rules.yaml",
            )
        )

    db.execute(delete(CompetitionCategoryRule))
    for item in policy.competition_category_rules_seed():
        db.add(
            CompetitionCategoryRule(
                competition_name_pattern=item.get("competition_name_pattern", ""),
                level=item.get("level", "国家级"),
                category=item.get("category", ""),
                score=float(item.get("score") or 0),
                note=item.get("note", ""),
                source=item.get("source") or "data/rules/competition_category_rules.yaml",
            )
        )

    db.flush()
    return {
        "expense_standards": len(policy.expense_standards_seed()),
        "award_point_rules": len(policy.award_point_rules_seed()),
        "category_rules": len(policy.competition_category_rules_seed()),
    }


# ============================================================
#  四、竞赛台账：参赛记录 / 队员 / 指导教师 / 获奖
# ============================================================
def seed_ledger(db) -> dict[str, int]:
    data = _load("ledger.json")
    comps = {c.code: c for c in db.execute(select(Competition)).scalars()}
    students = {s.student_no: s for s in db.execute(select(Student)).scalars()}
    teachers = {t.teacher_no: t for t in db.execute(select(Teacher)).scalars()}

    n_reg = n_member = n_award = 0
    for item in data.get("registrations", []):
        comp = comps.get(item["competition_code"])
        if comp is None:
            print(f"  [跳过] 未找到赛事：{item['competition_code']}（{item['code']}）")
            continue

        edition = db.execute(
            select(CompetitionEdition)
            .where(
                CompetitionEdition.competition_id == comp.id,
                CompetitionEdition.year == int(item["year"]),
            )
            .order_by(CompetitionEdition.id)
        ).scalars().first()
        track = None
        if edition is not None:
            track = db.execute(
                select(CompetitionTrack).where(
                    CompetitionTrack.edition_id == edition.id,
                    CompetitionTrack.name == item.get("track_name", ""),
                )
            ).scalars().first()

        reg = db.execute(select(Registration).where(Registration.code == item["code"])).scalars().first()
        if reg is None:
            reg = Registration(code=item["code"])
            db.add(reg)
        reg.competition_id = comp.id
        reg.edition_id = edition.id if edition else None
        reg.track_id = track.id if track else None
        reg.year = int(item["year"])
        reg.competition_name = comp.name
        reg.track_name = item.get("track_name", "")
        reg.competition_level = comp.level
        reg.competition_category = comp.category
        reg.team_name = item.get("team_name", "")
        reg.project_title = item.get("project_title", "")
        reg.project_brief = item.get("project_brief", "")
        reg.status = item.get("status", "报名中")
        reg.register_date = _date(item.get("register_date"))
        reg.finish_date = _date(item.get("finish_date"))
        reg.stage_reached = item.get("stage_reached", "")
        reg.lead_major = item.get("lead_major", "")
        reg.leader_name = item.get("leader_name", "")
        reg.mentor_names = item.get("mentor_names", "")
        reg.remark = item.get("remark", "")
        db.flush()
        n_reg += 1

        db.execute(delete(RegistrationMember).where(RegistrationMember.registration_id == reg.id))
        for m in item.get("members", []):
            stu = students.get(m.get("student_no", ""))
            db.add(
                RegistrationMember(
                    registration_id=reg.id,
                    student_id=stu.id if stu else None,
                    student_no=m.get("student_no", ""),
                    student_name=m.get("student_name", ""),
                    major_name=m.get("major_name", ""),
                    grade=m.get("grade", ""),
                    role=m.get("role", "队员"),
                    order_no=int(m.get("order_no") or 0) or 1,
                )
            )
            n_member += 1

        db.execute(delete(RegistrationMentor).where(RegistrationMentor.registration_id == reg.id))
        for idx, m in enumerate(item.get("mentors", []), 1):
            tea = teachers.get(m.get("teacher_no", ""))
            db.add(
                RegistrationMentor(
                    registration_id=reg.id,
                    teacher_id=tea.id if tea else None,
                    teacher_name=m.get("teacher_name", ""),
                    role=m.get("role", "指导教师"),
                    order_no=int(m.get("order_no") or idx),
                )
            )

        db.execute(delete(Award).where(Award.registration_id == reg.id))
        for aw in item.get("awards", []):
            award = Award(
                registration_id=reg.id,
                year=reg.year,
                award_year=int(aw.get("award_year") or reg.year),
                competition_name=comp.name,
                track_name=reg.track_name,
                award_level=aw.get("award_level", ""),
                award_grade=aw.get("award_grade", ""),
                competition_level=comp.level,
                project_title=aw.get("project_title") or reg.project_title,
                team_name=aw.get("team_name") or reg.team_name,
                students=aw.get("students", ""),
                majors=aw.get("majors", ""),
                mentors=aw.get("mentors", ""),
                issuing_body=aw.get("issuing_body", ""),
                certificate_no=aw.get("certificate_no", ""),
                award_date=_date(aw.get("award_date")),
                points=float(aw.get("points") or 0),
                remark=aw.get("remark", ""),
            )
            db.add(award)
            n_award += 1

        db.flush()

    return {"registrations": n_reg, "members": n_member, "awards": n_award}


def seed_all() -> dict[str, int]:
    init_db()
    summary: dict[str, int] = {}
    with session_scope() as db:
        summary.update(seed_master(db))
        summary.update(seed_competitions(db))
        summary.update(seed_rules(db))
        summary.update(seed_ledger(db))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="导入竞赛辅助服务种子数据")
    parser.add_argument("--skip-master", action="store_true", help="跳过专业/学生/教师")
    parser.add_argument("--skip-competitions", action="store_true", help="跳过赛事目录")
    parser.add_argument("--skip-rules", action="store_true", help="跳过费用与积分规则")
    parser.add_argument("--skip-ledger", action="store_true", help="跳过参赛与获奖台账")
    args = parser.parse_args()

    init_db()
    with session_scope() as db:
        summary: dict[str, int] = {}
        if not args.skip_master:
            summary.update(seed_master(db))
        if not args.skip_competitions:
            summary.update(seed_competitions(db))
        if not args.skip_rules:
            summary.update(seed_rules(db))
        if not args.skip_ledger:
            summary.update(seed_ledger(db))

    print("种子数据导入完成：")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
