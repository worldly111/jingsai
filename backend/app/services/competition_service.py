"""竞赛台账服务：赛事信息查询、竞赛推荐、备赛计划生成。

推荐与备赛的"规则"来自数据库（major_competition_fit）与 YAML 配置
（recommend_weights.yaml），新增赛事只需补数据，不需要改代码。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Award,
    AwardSetting,
    Competition,
    CompetitionEdition,
    CompetitionTrack,
    EditionMilestone,
    MajorCompetitionFit,
    Registration,
)
from .policy import recommend_weights
from .stats_service import StatsFilter, StatsService


class CompetitionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.cfg = recommend_weights()
        self.weights = self.cfg.get("weights", {})

    # ==========================================================
    #  台账查询
    # ==========================================================
    def list_competitions(self, *, keyword: str = "", level: str = "", active_only: bool = True) -> list[dict[str, Any]]:
        stmt = select(Competition)
        if active_only:
            stmt = stmt.where(Competition.is_active.is_(True))
        if level:
            stmt = stmt.where(Competition.level == level)
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    Competition.name.like(kw),
                    Competition.short_name.like(kw),
                    Competition.organizer.like(kw),
                    Competition.intro.like(kw),
                )
            )
        comps = list(self.db.execute(stmt.order_by(Competition.level, Competition.name)).scalars())
        return [self._brief(c) for c in comps]

    def _brief(self, c: Competition) -> dict[str, Any]:
        latest = self.latest_edition(c.id)
        return {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "short_name": c.short_name,
            "organizer": c.organizer,
            "level": c.level,
            "category": c.category,
            "competition_type": c.competition_type,
            "discipline_tags": c.discipline_tags or [],
            "official_url": c.official_url,
            "intro": c.intro,
            "target_audience": c.target_audience,
            "latest_year": latest.year if latest else None,
            "register_start": str(latest.register_start) if latest and latest.register_start else "",
            "register_end": str(latest.register_end) if latest and latest.register_end else "",
            "registration_fee": float(latest.registration_fee or 0) if latest else None,
            "team_size": f"{latest.team_size_min}-{latest.team_size_max} 人" if latest else "",
            "mentor_limit": latest.mentor_limit if latest else None,
            "status": latest.status if latest else "",
        }

    def latest_edition(self, competition_id: int, year: int | None = None) -> CompetitionEdition | None:
        stmt = select(CompetitionEdition).where(CompetitionEdition.competition_id == competition_id)
        if year:
            stmt = stmt.where(CompetitionEdition.year == year)
        return self.db.execute(stmt.order_by(CompetitionEdition.year.desc())).scalars().first()

    def detail(self, competition_id: int, year: int | None = None) -> dict[str, Any] | None:
        comp = self.db.get(Competition, competition_id)
        if not comp:
            return None
        edition = self.latest_edition(competition_id, year)
        data = self._brief(comp)
        data["editions"] = [
            {
                "id": e.id,
                "year": e.year,
                "edition_name": e.edition_name,
                "notice_title": e.notice_title,
                "notice_no": e.notice_no,
                "status": e.status,
                "register_start": str(e.register_start) if e.register_start else "",
                "register_end": str(e.register_end) if e.register_end else "",
                "competition_period": e.competition_period,
            }
            for e in self.db.execute(
                select(CompetitionEdition)
                .where(CompetitionEdition.competition_id == competition_id)
                .order_by(CompetitionEdition.year.desc())
            ).scalars()
        ]
        if not edition:
            data.update({"tracks": [], "milestones": [], "award_settings": [], "required_materials": [], "eligibility": ""})
            return data

        data.update(
            {
                "edition_id": edition.id,
                "year": edition.year,
                "edition_name": edition.edition_name,
                "notice_title": edition.notice_title,
                "notice_no": edition.notice_no,
                "issued_by": edition.issued_by,
                "issued_date": str(edition.issued_date) if edition.issued_date else "",
                "register_start": str(edition.register_start) if edition.register_start else "",
                "register_end": str(edition.register_end) if edition.register_end else "",
                "competition_period": edition.competition_period,
                "eligibility": edition.eligibility,
                "team_size_min": edition.team_size_min,
                "team_size_max": edition.team_size_max,
                "mentor_limit": edition.mentor_limit,
                "registration_fee": float(edition.registration_fee or 0),
                "fee_note": edition.fee_note,
                "required_materials": edition.required_materials or [],
                "material_note": edition.material_note,
                "source_ref": edition.source_ref,
                "tracks": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "description": t.description,
                        "requirements": t.requirements or [],
                        "team_size": f"{t.team_size_min or edition.team_size_min}-{t.team_size_max or edition.team_size_max} 人",
                        "fee": float(t.fee) if t.fee is not None else None,
                        "discipline_tags": t.discipline_tags or [],
                    }
                    for t in self.db.execute(
                        select(CompetitionTrack).where(CompetitionTrack.edition_id == edition.id)
                    ).scalars()
                ],
                "milestones": [
                    {
                        "name": m.name,
                        "stage": m.stage,
                        "start_date": str(m.start_date) if m.start_date else "",
                        "end_date": str(m.end_date) if m.end_date else "",
                        "note": m.note,
                    }
                    for m in self.db.execute(
                        select(EditionMilestone)
                        .where(EditionMilestone.edition_id == edition.id)
                        .order_by(EditionMilestone.start_date)
                    ).scalars()
                ],
                "award_settings": [
                    {
                        "award_level": a.award_level,
                        "category": a.category,
                        "ratio": a.ratio,
                        "quantity": a.quantity,
                        "prize": a.prize,
                        "note": a.note,
                    }
                    for a in self.db.execute(
                        select(AwardSetting).where(AwardSetting.edition_id == edition.id)
                    ).scalars()
                ],
                "ledger": self.ledger_summary(comp.name),
            }
        )
        return data

    def ledger_summary(self, competition_name: str, *, years: int = 5) -> dict[str, Any]:
        """该赛事在学院的历年参赛与获奖情况（结构化数据，供回答引用）。"""
        start_year = date.today().year - years
        reg_stmt = select(func.count(Registration.id)).where(
            Registration.competition_name == competition_name, Registration.year >= start_year
        )
        reg_count = int(self.db.execute(reg_stmt).scalar() or 0)

        rows = list(
            self.db.execute(
                select(Award.award_year, Award.award_level, func.count(Award.id))
                .where(Award.competition_name == competition_name, Award.award_year >= start_year)
                .group_by(Award.award_year, Award.award_level)
            ).all()
        )
        by_year: dict[int, dict[str, int]] = {}
        for year, level, count in rows:
            by_year.setdefault(int(year), {})[level] = int(count)
        total_awards = sum(sum(v.values()) for v in by_year.values())
        return {
            "competition_name": competition_name,
            "registrations": reg_count,
            "awards": total_awards,
            "by_year": [{"year": y, **v} for y, v in sorted(by_year.items())],
        }

    def upcoming_milestones(self, *, days: int = 180, limit: int = 30) -> list[dict[str, Any]]:
        today = date.today()
        end = today + timedelta(days=days)
        rows = self.db.execute(
            select(EditionMilestone, CompetitionEdition, Competition)
            .join(CompetitionEdition, EditionMilestone.edition_id == CompetitionEdition.id)
            .join(Competition, CompetitionEdition.competition_id == Competition.id)
            .where(EditionMilestone.end_date.is_not(None))
            .order_by(EditionMilestone.end_date)
        ).all()
        out: list[dict[str, Any]] = []
        for m, e, c in rows:
            if not m.end_date:
                continue
            delta = (m.end_date - today).days
            if -7 <= delta <= days and m.end_date <= end:
                out.append(
                    {
                        "competition_id": c.id,
                        "competition_name": c.name,
                        "level": c.level,
                        "year": e.year,
                        "milestone": m.name,
                        "stage": m.stage,
                        "date": str(m.end_date),
                        "days_left": delta,
                        "note": m.note,
                    }
                )
        out.sort(key=lambda x: x["days_left"])
        return out[:limit]

    # ==========================================================
    #  竞赛推荐
    # ==========================================================
    def recommend(self, profile: dict[str, Any], *, top_n: int = 6) -> dict[str, Any]:
        major = str(profile.get("major") or "").strip()
        grade = str(profile.get("grade") or "").strip()
        tags = [str(t).strip() for t in (profile.get("tech_tags") or []) if str(t).strip()]
        has_project = bool(profile.get("has_project")) or bool(str(profile.get("project_title") or "").strip())
        preferred_level = str(profile.get("preferred_level") or "").strip()
        participated = {str(x) for x in (profile.get("participated") or [])}

        grade_map = self.cfg.get("grade_map", {})
        level_bonus_map = self.cfg.get("level_bonus_map", {})
        reasons_cfg = self.cfg.get("reasons", {})
        grade_key = next((k for k in grade_map if grade and (k in grade or grade in k)), "")
        allowed_diff = grade_map.get(grade_key, ["入门", "中", "高"])

        comps = list(self.db.execute(select(Competition).where(Competition.is_active.is_(True))).scalars())
        fits = list(self.db.execute(select(MajorCompetitionFit)).scalars())
        fit_by_comp: dict[int, list[MajorCompetitionFit]] = {}
        for f in fits:
            fit_by_comp.setdefault(f.competition_id, []).append(f)

        today = date.today()
        results: list[dict[str, Any]] = []

        for comp in comps:
            rows = fit_by_comp.get(comp.id, [])
            breakdown: dict[str, float] = {}
            reasons: list[str] = []

            # 1) 专业适配
            major_fit = 0.0
            for r in rows:
                if r.match_type == "major" and major and (r.match_value in major or major in r.match_value):
                    major_fit = max(major_fit, r.fit_score)
            if not major_fit and comp.discipline_tags:
                for tag in comp.discipline_tags:
                    if major and tag and (tag in major or major in tag):
                        major_fit = max(major_fit, 0.75)
            breakdown["major_fit"] = round(major_fit, 3)
            if major_fit >= 0.8:
                reasons.append(reasons_cfg.get("major", "与你的专业方向高度相关"))

            # 2) 技术方向匹配
            tag_fit = 0.0
            hit_tags: list[str] = []
            for r in rows:
                if r.match_type == "tech_tag":
                    for tag in tags:
                        if tag and (tag in r.match_value or r.match_value in tag):
                            if r.fit_score > tag_fit:
                                tag_fit = r.fit_score
                            hit_tags.append(tag)
            for tag in tags:
                if tag in (comp.discipline_tags or []) or tag in comp.name:
                    tag_fit = max(tag_fit, 0.8)
                    hit_tags.append(tag)
            breakdown["tech_tag_fit"] = round(min(tag_fit, 1.0), 3)
            if hit_tags:
                reasons.append(reasons_cfg.get("tech_tag", "与你关注的技术方向直接对应").format(tag=hit_tags[0]))

            # 3) 年级适配
            fit_row = next((r for r in rows if r.match_type in ("major", "tech_tag")), None)
            difficulty = fit_row.difficulty if fit_row else "中"
            grade_fit = 1.0 if difficulty in allowed_diff else 0.45
            if fit_row and fit_row.recommended_grade and grade and fit_row.recommended_grade in grade:
                grade_fit = 1.0
            breakdown["grade_fit"] = round(grade_fit, 3)
            if grade_fit >= 1.0 and grade:
                reasons.append(
                    reasons_cfg.get("grade", "适合{grade}学生的难度档位（{difficulty}）").format(
                        grade=grade, difficulty=difficulty
                    )
                )

            # 4) 项目情况
            ctype = comp.competition_type or ""
            if has_project and any(k in ctype for k in ("创新创业", "作品", "设计")):
                project_fit = 1.0
                reasons.append(reasons_cfg.get("project", "你已有项目/作品基础，可直接改编为参赛作品"))
            elif has_project:
                project_fit = 0.7
            elif any(k in ctype for k in ("程序设计", "算法", "个人赛")):
                project_fit = 0.85
                reasons.append(reasons_cfg.get("no_project", "无项目基础也可以参加，适合作为入门赛事积累经验"))
            else:
                project_fit = 0.5
            breakdown["project_status"] = round(project_fit, 3)

            # 5) 级别加成
            level_b = float(level_bonus_map.get(comp.level, 0.5))
            if preferred_level and preferred_level == comp.level:
                level_b = min(1.0, level_b + 0.3)
            breakdown["level_bonus"] = round(level_b, 3)

            # 6) 时间临近加成
            edition = self.latest_edition(comp.id)
            fresh = 0.3
            deadline_note = ""
            if edition and edition.register_end:
                days_left = (edition.register_end - today).days
                if 0 <= days_left <= 90:
                    fresh = 1.0
                    deadline_note = reasons_cfg.get("deadline", "报名截止 {date}，还有 {days} 天").format(
                        date=edition.register_end, days=days_left
                    )
                    reasons.append(deadline_note)
                elif days_left > 90:
                    fresh = 0.6
            breakdown["fresh_bonus"] = round(fresh, 3)

            score = sum(breakdown.get(k, 0.0) * float(self.weights.get(k, 0.0)) for k in self.weights)
            if score <= 0.15:
                continue

            ledger = self.ledger_summary(comp.name)
            results.append(
                {
                    "competition_id": comp.id,
                    "name": comp.name,
                    "short_name": comp.short_name,
                    "level": comp.level,
                    "category": comp.category,
                    "type": comp.competition_type,
                    "difficulty": difficulty,
                    "score": round(min(score, 1.0), 3),
                    "score_breakdown": breakdown,
                    "reasons": [r for r in dict.fromkeys(reasons) if r],
                    "fit_reason": fit_row.reason if fit_row else "",
                    "recommended_grade": fit_row.recommended_grade if fit_row else "",
                    "official_url": comp.official_url,
                    "latest_year": edition.year if edition else None,
                    "register_end": str(edition.register_end) if edition and edition.register_end else "",
                    "registration_fee": float(edition.registration_fee or 0) if edition else None,
                    "team_size": f"{edition.team_size_min}-{edition.team_size_max} 人" if edition else "",
                    "required_materials": (edition.required_materials or []) if edition else [],
                    "college_ledger": {
                        "registrations": ledger["registrations"],
                        "awards": ledger["awards"],
                    },
                    "participated_before": comp.name in participated or (comp.short_name or "") in participated,
                }
            )

        results.sort(key=lambda x: (-x["score"], -x["college_ledger"]["awards"]))
        selected = results[:top_n]
        return {
            "profile": {
                "major": major,
                "grade": grade,
                "tech_tags": tags,
                "has_project": has_project,
                "preferred_level": preferred_level,
            },
            "recommendations": selected,
            "method": "专业适配度 × 技术方向匹配 × 年级适配 × 项目情况 × 级别与时间加成（权重见 data/rules/recommend_weights.yaml）",
            "total_candidates": len(results),
        }

    # ==========================================================
    #  备赛计划
    # ==========================================================
    def prep_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        comp: Competition | None = None
        edition: CompetitionEdition | None = None

        if payload.get("competition_id"):
            comp = self.db.get(Competition, int(payload["competition_id"]))
        elif payload.get("competition_name"):
            name = str(payload["competition_name"])
            stmt = select(Competition).where(
                or_(Competition.name.like(f"%{name}%"), Competition.short_name.like(f"%{name}%"))
            )
            comp = self.db.execute(stmt).scalars().first()
        if not comp:
            raise ValueError("未找到对应的赛事，请确认赛事名称或先从赛事台账中选择")

        edition = self.latest_edition(comp.id, payload.get("year"))
        target = _parse_date(payload.get("target_date"))
        if not target and edition:
            target = edition.register_end or None
        if not target:
            target = date.today() + timedelta(days=60)

        today = date.today()
        days_left = (target - today).days
        expired = days_left < 0
        stages_cfg = self.cfg.get("prep_stages", [])
        ordered: list[dict[str, Any]] = []
        if not expired:
            # 各阶段按剩余窗口连续切分：ratio 表示该阶段结束时剩余时间的占比
            for i, stage in enumerate(stages_cfg):
                next_ratio = float(stages_cfg[i + 1].get("offset_ratio", 0.0)) if i + 1 < len(stages_cfg) else 0.0
                stage_end = target - timedelta(days=int(days_left * next_ratio))
                stage_start = today if i == 0 else date.fromisoformat(ordered[-1]["end"])
                ordered.append(
                    {
                        "stage": stage.get("name"),
                        "start": str(stage_start),
                        "end": str(stage_end),
                        "tasks": list(stage.get("tasks") or []),
                    }
                )

        materials = list(edition.required_materials or []) if edition else []
        material_advice = self._material_advice(materials)

        notes: list[str] = []
        if edition:
            if expired:
                notes.append(
                    f"所查询届次的报名截止日期 {target} 已过去 {abs(days_left)} 天，"
                    "不再生成倒排时间表；以下材料与组队要求供下一届备赛参考。"
                )
            if edition.register_start and edition.register_end:
                notes.append(f"报名时间：{edition.register_start} 至 {edition.register_end}")
            if edition.eligibility:
                notes.append(f"参赛资格：{edition.eligibility}")
            if edition.team_size_min:
                notes.append(f"组队要求：{edition.team_size_min}-{edition.team_size_max} 人，指导教师上限 {edition.mentor_limit} 人")
            if edition.registration_fee:
                notes.append(f"报名费：{float(edition.registration_fee):.2f} 元，{edition.fee_note or ''}".strip())
            if edition.source_ref:
                notes.append(f"规程出处：{edition.source_ref}")

        ledger = self.ledger_summary(comp.name)
        if ledger["registrations"]:
            notes.append(
                f"学院近 5 年参加该赛事 {ledger['registrations']} 队次，累计获奖 {ledger['awards']} 项"
            )

        tracks = []
        if edition:
            tracks = [
                {"name": t.name, "requirements": t.requirements or [], "description": t.description}
                for t in self.db.execute(
                    select(CompetitionTrack).where(CompetitionTrack.edition_id == edition.id)
                ).scalars()
            ]

        return {
            "competition": {
                "id": comp.id,
                "name": comp.name,
                "level": comp.level,
                "category": comp.category,
                "organizer": comp.organizer,
                "official_url": comp.official_url,
            },
            "edition": {
                "year": edition.year if edition else None,
                "name": edition.edition_name if edition else "",
                "register_start": str(edition.register_start) if edition and edition.register_start else "",
                "register_end": str(edition.register_end) if edition and edition.register_end else "",
                "competition_period": edition.competition_period if edition else "",
                "notice_title": edition.notice_title if edition else "",
            }
            if edition
            else None,
            "target_date": str(target),
            "days_left": days_left,
            "expired": expired,
            "timeline": ordered,
            "materials": material_advice,
            "tracks": tracks,
            "notes": notes,
            "ledger": ledger,
            "checklist_total": sum(len(s["tasks"]) for s in ordered) + len(material_advice),
        }

    def _material_advice(self, materials: list[Any]) -> list[dict[str, Any]]:
        tips = {
            "报名表": "从赛事系统导出后核对学号、专业、联系方式，避免格式错位",
            "作品文档": "按赛项模板撰写，注意匿名要求（常见规定：正文与演示材料中不得出现学校名与教师姓名）",
            "演示视频": "控制在规定时长内，开头 15 秒说明作品要解决的问题",
            "源码": "整理为可编译运行的仓库，附环境说明与依赖清单",
            "PPT": "控制在评审规定页数内，多用图表、少用大段文字",
            "作品说明": "重点写清创新点与验证结果，避免只有功能罗列",
            "承诺书": "需全体成员与指导教师签字，扫描后随材料一并提交",
            "身份证明": "部分赛事需要教务部门盖章的队员与指导教师名单",
            "论文": "按模板排版，图表编号连续，参考文献格式统一",
        }
        out: list[dict[str, Any]] = []
        for item in materials:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("item") or "")
                note = str(item.get("note") or "")
            else:
                name = str(item)
                note = ""
            if not name:
                continue
            advice = note or next((v for k, v in tips.items() if k in name), "按赛事通知要求准备，注意提交格式与截止时间")
            out.append({"name": name, "advice": advice})
        return out


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None