"""统计分析与可视化。

所有统计一律以结构化业务数据（registrations / awards / registration_members /
registration_mentors）为唯一数据源，不由大模型生成任何数字。
查询条件由自然语言解析而来，聚合计算使用 Pandas，图表使用 ECharts 配置输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Award, AwardPointRule, Competition, Registration

AWARD_ORDER = ["特等奖", "一等奖", "二等奖", "三等奖", "优胜奖", "入围奖", "其他"]
LEVEL_ORDER = ["国家级", "省级", "校级"]


@dataclass
class StatsFilter:
    years: list[int] = field(default_factory=list)
    competitions: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    award_levels: list[str] = field(default_factory=list)
    majors: list[str] = field(default_factory=list)
    teachers: list[str] = field(default_factory=list)
    students: list[str] = field(default_factory=list)
    tracks: list[str] = field(default_factory=list)
    keyword: str = ""

    def describe(self) -> str:
        parts = []
        if self.years:
            parts.append(f"年度 {'、'.join(str(y) for y in self.years)}")
        if self.competitions:
            parts.append(f"赛事 {'、'.join(self.competitions)}")
        if self.levels:
            parts.append(f"级别 {'、'.join(self.levels)}")
        if self.categories:
            parts.append(f"类别 {'、'.join(self.categories)}")
        if self.award_levels:
            parts.append(f"获奖等级 {'、'.join(self.award_levels)}")
        if self.majors:
            parts.append(f"专业 {'、'.join(self.majors)}")
        if self.teachers:
            parts.append(f"指导教师 {'、'.join(self.teachers)}")
        if self.students:
            parts.append(f"学生 {'、'.join(self.students)}")
        if self.tracks:
            parts.append(f"赛道 {'、'.join(self.tracks)}")
        if self.keyword:
            parts.append(f"关键词「{self.keyword}」")
        return "；".join(parts) if parts else "全部数据"

    def to_dict(self) -> dict[str, Any]:
        return {
            "years": self.years,
            "competitions": self.competitions,
            "levels": self.levels,
            "categories": self.categories,
            "award_levels": self.award_levels,
            "majors": self.majors,
            "teachers": self.teachers,
            "students": self.students,
            "tracks": self.tracks,
            "keyword": self.keyword,
        }


class StatsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ==========================================================
    #  数据装载
    # ==========================================================
    def load_frames(self, flt: StatsFilter) -> tuple[pd.DataFrame, pd.DataFrame]:
        reg_stmt = select(Registration)
        reg_stmt = _apply_filters_reg(reg_stmt, flt)
        regs = list(self.db.execute(reg_stmt).scalars())
        reg_rows = [
            {
                "registration_id": r.id,
                "year": r.year,
                "competition_name": r.competition_name,
                "track_name": r.track_name,
                "competition_level": r.competition_level,
                "competition_category": r.competition_category,
                "team_name": r.team_name,
                "project_title": r.project_title,
                "status": r.status,
                "stage_reached": r.stage_reached,
                "lead_major": r.lead_major,
                "mentor_names": r.mentor_names,
                "member_count": len(r.members),
                "members": "、".join(m.student_name for m in r.members),
                "majors": "、".join(sorted({m.major_name for m in r.members if m.major_name})),
            }
            for r in regs
        ]
        df_reg = pd.DataFrame(reg_rows)

        aw_stmt = select(Award)
        aw_stmt = _apply_filters_award(aw_stmt, flt)
        awards = list(self.db.execute(aw_stmt).scalars())
        aw_rows = [
            {
                "award_id": a.id,
                "registration_id": a.registration_id,
                "year": a.award_year or a.year,
                "competition_name": a.competition_name,
                "track_name": a.track_name,
                "award_level": a.award_level,
                "award_grade": a.award_grade or a.competition_level,
                "competition_level": a.competition_level,
                "project_title": a.project_title,
                "team_name": a.team_name,
                "students": a.students,
                "majors": a.majors,
                "mentors": a.mentors,
                "points": float(a.points or 0),
                "award_date": str(a.award_date) if a.award_date else "",
            }
            for a in awards
        ]
        df_aw = pd.DataFrame(aw_rows)
        return df_reg, df_aw

    # ==========================================================
    #  总览
    # ==========================================================
    def overview(self, flt: StatsFilter | None = None) -> dict[str, Any]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)

        reg_count = int(len(df_reg))
        participant_count = int(df_reg["member_count"].sum()) if not df_reg.empty else 0
        award_count = int(len(df_aw))
        student_set: set[str] = set()
        for names in (df_aw["students"].tolist() if not df_aw.empty else []):
            student_set.update(x for x in str(names).split("、") if x)
        for names in (df_reg["members"].tolist() if not df_reg.empty else []):
            student_set.update(x for x in str(names).split("、") if x)

        teacher_set: set[str] = set()
        for names in (df_reg["mentor_names"].tolist() if not df_reg.empty else []):
            teacher_set.update(x for x in str(names).replace("，", "、").replace(",", "、").split("、") if x)

        award_rate = round(award_count / reg_count * 100, 1) if reg_count else 0.0
        high_level = 0
        if not df_aw.empty:
            high_level = int(df_aw[df_aw["award_level"].isin(["特等奖", "一等奖"])].shape[0])

        return {
            "filter": flt.describe(),
            "filter_detail": flt.to_dict(),
            "registrations": reg_count,
            "participants": participant_count,
            "awards": award_count,
            "award_rate": award_rate,
            "high_level_awards": high_level,
            "students": len(student_set),
            "teachers": len(teacher_set),
            "competitions": int(df_reg["competition_name"].nunique()) if not df_reg.empty else 0,
            "years": sorted({int(y) for y in df_reg["year"].tolist()}) if not df_reg.empty else [],
            "data_source": "结构化业务数据（registrations / awards）",
        }

    # ==========================================================
    #  多维统计
    # ==========================================================
    def by_year(self, flt: StatsFilter | None = None) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)
        if df_reg.empty and df_aw.empty:
            return []

        reg = df_reg.groupby("year").size().rename("参赛数") if not df_reg.empty else pd.Series(dtype=int)
        aw = df_aw.groupby("year").size().rename("获奖数") if not df_aw.empty else pd.Series(dtype=int)
        high = (
            df_aw[df_aw["award_level"].isin(["特等奖", "一等奖"])].groupby("year").size().rename("高等级奖")
            if not df_aw.empty
            else pd.Series(dtype=int)
        )
        people = (
            df_reg.groupby("year")["member_count"].sum().rename("参赛人次")
            if not df_reg.empty
            else pd.Series(dtype=int)
        )
        df = pd.concat([reg, aw, high, people], axis=1).fillna(0).reset_index()
        df = df.sort_values("year")
        out = []
        for _, row in df.iterrows():
            reg_n = int(row.get("参赛数", 0))
            aw_n = int(row.get("获奖数", 0))
            out.append(
                {
                    "year": int(row["year"]),
                    "registrations": reg_n,
                    "awards": aw_n,
                    "high_level_awards": int(row.get("高等级奖", 0)),
                    "participants": int(row.get("参赛人次", 0)),
                    "award_rate": round(aw_n / reg_n * 100, 1) if reg_n else 0.0,
                }
            )
        return out

    def by_competition(self, flt: StatsFilter | None = None, *, top: int = 20) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        _, df_aw = self.load_frames(flt)
        df_reg, _ = self.load_frames(flt)
        if df_reg.empty:
            return []
        reg = df_reg.groupby("competition_name").size().rename("registrations")
        aw = df_aw.groupby("competition_name").size().rename("awards") if not df_aw.empty else pd.Series(dtype=int)
        high = (
            df_aw[df_aw["award_level"].isin(["特等奖", "一等奖"])].groupby("competition_name").size().rename("high")
            if not df_aw.empty
            else pd.Series(dtype=int)
        )
        df = pd.concat([reg, aw, high], axis=1).fillna(0).reset_index()
        df = df.sort_values("awards", ascending=False).head(top)
        return [
            {
                "competition_name": row["competition_name"],
                "registrations": int(row["registrations"]),
                "awards": int(row["awards"]),
                "high_level_awards": int(row.get("high", 0)),
                "award_rate": round(int(row["awards"]) / int(row["registrations"]) * 100, 1)
                if int(row["registrations"])
                else 0.0,
            }
            for _, row in df.iterrows()
        ]

    def by_major(self, flt: StatsFilter | None = None, *, top: int = 30) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)
        rows: list[dict[str, Any]] = []

        reg_counter: dict[str, int] = {}
        for majors in (df_reg["majors"].tolist() if not df_reg.empty else []):
            for m in str(majors).split("、"):
                if m:
                    reg_counter[m] = reg_counter.get(m, 0) + 1

        aw_counter: dict[str, int] = {}
        for majors in (df_aw["majors"].tolist() if not df_aw.empty else []):
            for m in str(majors).replace("，", "、").replace(",", "、").split("、"):
                if m:
                    aw_counter[m] = aw_counter.get(m, 0) + 1

        for major in sorted(set(reg_counter) | set(aw_counter)):
            r = reg_counter.get(major, 0)
            a = aw_counter.get(major, 0)
            rows.append(
                {
                    "major": major,
                    "registrations": r,
                    "awards": a,
                    "award_rate": round(a / r * 100, 1) if r else 0.0,
                }
            )
        rows.sort(key=lambda x: (-x["awards"], -x["registrations"]))
        return rows[:top]

    def by_award_level(self, flt: StatsFilter | None = None) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        _, df_aw = self.load_frames(flt)
        if df_aw.empty:
            return []
        df = df_aw.groupby(["award_level", "award_grade"]).size().rename("count").reset_index()
        total = int(df["count"].sum())
        rows = [
            {
                "award_level": row["award_level"],
                "award_grade": row["award_grade"],
                "count": int(row["count"]),
                "ratio": round(int(row["count"]) / total * 100, 1) if total else 0.0,
            }
            for _, row in df.iterrows()
        ]
        rows.sort(key=lambda x: (LEVEL_ORDER.index(x["award_grade"]) if x["award_grade"] in LEVEL_ORDER else 9,
                                 AWARD_ORDER.index(x["award_level"]) if x["award_level"] in AWARD_ORDER else 9))
        return rows

    def by_level(self, flt: StatsFilter | None = None) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)
        if df_reg.empty:
            return []
        reg = df_reg.groupby("competition_level").size().rename("registrations")
        aw = (
            df_aw.groupby("award_grade").size().rename("awards")
            if not df_aw.empty
            else pd.Series(dtype=int)
        )
        df = pd.concat([reg, aw], axis=1).fillna(0).reset_index()
        df.columns = ["level", "registrations", "awards"]
        return [
            {
                "level": row["level"] or "未认定",
                "registrations": int(row["registrations"]),
                "awards": int(row["awards"]),
            }
            for _, row in df.iterrows()
        ]

    def by_teacher(self, flt: StatsFilter | None = None, *, top: int = 30) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)
        rows_map: dict[str, dict[str, Any]] = {}

        def touch(name: str) -> dict[str, Any]:
            if name not in rows_map:
                rows_map[name] = {
                    "teacher": name,
                    "registrations": 0,
                    "awards": 0,
                    "high_level_awards": 0,
                    "students": set(),
                    "competitions": set(),
                }
            return rows_map[name]

        for _, row in (df_reg.iterrows() if not df_reg.empty else []):
            for name in _split_names(row["mentor_names"]):
                item = touch(name)
                item["registrations"] += 1
                if row["competition_name"]:
                    item["competitions"].add(row["competition_name"])

        for _, row in (df_aw.iterrows() if not df_aw.empty else []):
            for name in _split_names(row["mentors"]):
                item = touch(name)
                item["awards"] += 1
                if row["award_level"] in ("特等奖", "一等奖"):
                    item["high_level_awards"] += 1
                for stu in _split_names(row["students"]):
                    item["students"].add(stu)

        out = [
            {
                "teacher": v["teacher"],
                "registrations": v["registrations"],
                "awards": v["awards"],
                "high_level_awards": v["high_level_awards"],
                "student_count": len(v["students"]),
                "competition_count": len(v["competitions"]),
            }
            for v in rows_map.values()
        ]
        out.sort(key=lambda x: (-x["awards"], -x["registrations"]))
        return out[:top]

    def by_student(self, flt: StatsFilter | None = None, *, top: int = 50) -> list[dict[str, Any]]:
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)
        rows_map: dict[str, dict[str, Any]] = {}

        for _, row in (df_reg.iterrows() if not df_reg.empty else []):
            for name in _split_names(row["members"]):
                item = rows_map.setdefault(name, {"student": name, "registrations": 0, "awards": 0, "majors": "", "points": 0.0})
                item["registrations"] += 1
        for _, row in (df_aw.iterrows() if not df_aw.empty else []):
            for name in _split_names(row["students"]):
                item = rows_map.setdefault(name, {"student": name, "registrations": 0, "awards": 0, "majors": "", "points": 0.0})
                item["awards"] += 1
                item["majors"] = row["majors"] or item["majors"]
                item["points"] += float(row["points"] or 0)

        out = list(rows_map.values())
        for item in out:
            item["points"] = round(item["points"], 1)
            item["award_rate"] = round(item["awards"] / item["registrations"] * 100, 1) if item["registrations"] else 0.0
        out.sort(key=lambda x: (-x["awards"], -x["points"], -x["registrations"]))
        return out[:top]

    def teacher_workload(self, flt: StatsFilter | None = None) -> list[dict[str, Any]]:
        """按 award_point_rules 折算教师指导工作量与获奖积分。"""
        rules = list(self.db.execute(select(AwardPointRule)).scalars())
        rule_map = {(r.award_grade, r.award_level): r for r in rules}
        flt = flt or StatsFilter()
        _, df_aw = self.load_frames(flt)
        if df_aw.empty:
            return []

        acc: dict[str, dict[str, Any]] = {}
        for _, row in df_aw.iterrows():
            rule = rule_map.get((row["award_grade"], row["award_level"]))
            workload = float(rule.teacher_workload) if rule else 0.0
            student_points = float(rule.student_points) if rule else float(row["points"] or 0)
            for name in _split_names(row["mentors"]):
                item = acc.setdefault(
                    name,
                    {"teacher": name, "workload": 0.0, "awards": 0, "student_points": 0.0, "detail": []},
                )
                item["workload"] += workload
                item["awards"] += 1
                item["student_points"] += student_points
                item["detail"].append(
                    {
                        "competition": row["competition_name"],
                        "award_level": row["award_level"],
                        "award_grade": row["award_grade"],
                        "rule": rule.note if rule else "未配置折算规则",
                        "workload": workload,
                    }
                )

        out = list(acc.values())
        for item in out:
            item["workload"] = round(item["workload"], 1)
            item["student_points"] = round(item["student_points"], 1)
        out.sort(key=lambda x: -x["workload"])
        return out

    def cross(self, dim1: str, dim2: str, flt: StatsFilter | None = None) -> dict[str, Any]:
        """交叉统计，返回可直接渲染成表格/热力图的结构。"""
        flt = flt or StatsFilter()
        df_reg, df_aw = self.load_frames(flt)

        frames = []
        if not df_reg.empty:
            tmp = df_reg.copy()
            tmp["value"] = 1
            frames.append(tmp[[dim1, dim2, "value"]])
        if not frames:
            return {"dim1": dim1, "dim2": dim2, "rows": [], "columns": [], "matrix": []}

        df = pd.concat(frames)
        df[dim1] = df[dim1].fillna("未填写")
        df[dim2] = df[dim2].fillna("未填写")
        pivot = df.pivot_table(index=dim1, columns=dim2, values="value", aggfunc="sum", fill_value=0)
        return {
            "dim1": dim1,
            "dim2": dim2,
            "rows": [str(x) for x in pivot.index.tolist()],
            "columns": [str(x) for x in pivot.columns.tolist()],
            "matrix": pivot.astype(int).values.tolist(),
        }

    def year_major_awards(self, flt: StatsFilter | None = None) -> dict[str, Any]:
        flt = flt or StatsFilter()
        _, df_aw = self.load_frames(flt)
        if df_aw.empty:
            return {"rows": [], "columns": [], "matrix": []}
        rows = sorted({int(y) for y in df_aw["year"].tolist()})
        majors: list[str] = []
        for m in df_aw["majors"].tolist():
            for x in str(m).replace("，", "、").replace(",", "、").split("、"):
                if x and x not in majors:
                    majors.append(x)
        matrix: list[list[int]] = []
        for y in rows:
            line = []
            for major in majors:
                cnt = sum(
                    1
                    for _, r in df_aw[df_aw["year"] == y].iterrows()
                    if major in str(r["majors"])
                )
                line.append(cnt)
            matrix.append(line)
        return {"rows": rows, "columns": majors, "matrix": matrix}

    # ==========================================================
    #  ECharts 配置
    # ==========================================================
    def chart(self, kind: str, flt: StatsFilter | None = None) -> dict[str, Any]:
        flt = flt or StatsFilter()
        if kind == "trend":
            data = self.by_year(flt)
            return {
                "title": {"text": "年度参赛与获奖趋势", "subtext": flt.describe()},
                "tooltip": {"trigger": "axis"},
                "legend": {"data": ["参赛数", "获奖数", "参赛人次", "获奖率(%)"]},
                "xAxis": {"type": "category", "data": [str(d["year"]) for d in data]},
                "yAxis": [{"type": "value", "name": "队数"}, {"type": "value", "name": "百分比(%)", "max": 100}],
                "series": [
                    {"name": "参赛数", "type": "bar", "data": [d["registrations"] for d in data]},
                    {"name": "获奖数", "type": "bar", "data": [d["awards"] for d in data]},
                    {"name": "参赛人次", "type": "line", "smooth": True, "data": [d["participants"] for d in data]},
                    {
                        "name": "获奖率(%)",
                        "type": "line",
                        "yAxisIndex": 1,
                        "smooth": True,
                        "data": [d["award_rate"] for d in data],
                    },
                ],
            }
        if kind == "competition":
            data = self.by_competition(flt)
            return {
                "title": {"text": "各赛事获奖情况", "subtext": flt.describe()},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "legend": {"data": ["参赛数", "获奖数", "高等级奖"]},
                "grid": {"left": 60, "right": 30, "bottom": 90},
                "xAxis": {"type": "category", "data": [d["competition_name"] for d in data], "axisLabel": {"rotate": 30}},
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "参赛数", "type": "bar", "data": [d["registrations"] for d in data]},
                    {"name": "获奖数", "type": "bar", "data": [d["awards"] for d in data]},
                    {"name": "高等级奖", "type": "bar", "data": [d["high_level_awards"] for d in data]},
                ],
            }
        if kind == "award_level":
            data = self.by_award_level(flt)
            return {
                "title": {"text": "获奖等级构成", "subtext": flt.describe()},
                "tooltip": {"trigger": "item", "formatter": "{b}: {c} 项 ({d}%)"},
                "legend": {"orient": "vertical", "left": "left"},
                "series": [
                    {
                        "name": "获奖等级",
                        "type": "pie",
                        "radius": ["40%", "68%"],
                        "data": [
                            {"name": f"{d['award_grade']}{d['award_level']}", "value": d["count"]} for d in data
                        ],
                    }
                ],
            }
        if kind == "major":
            data = self.by_major(flt)
            return {
                "title": {"text": "各专业参赛与获奖", "subtext": flt.describe()},
                "tooltip": {"trigger": "axis"},
                "legend": {"data": ["参赛数", "获奖数", "获奖率(%)"]},
                "xAxis": {"type": "category", "data": [d["major"] for d in data], "axisLabel": {"rotate": 30}},
                "yAxis": [{"type": "value"}, {"type": "value", "max": 100}],
                "series": [
                    {"name": "参赛数", "type": "bar", "data": [d["registrations"] for d in data]},
                    {"name": "获奖数", "type": "bar", "data": [d["awards"] for d in data]},
                    {
                        "name": "获奖率(%)",
                        "type": "line",
                        "yAxisIndex": 1,
                        "smooth": True,
                        "data": [d["award_rate"] for d in data],
                    },
                ],
            }
        if kind == "teacher":
            data = self.by_teacher(flt)[:15]
            return {
                "title": {"text": "指导教师获奖排行", "subtext": flt.describe()},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "legend": {"data": ["指导获奖数", "高等级奖"]},
                "grid": {"left": 100, "right": 40, "bottom": 40},
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category", "data": [d["teacher"] for d in data][::-1]},
                "series": [
                    {
                        "name": "指导获奖数",
                        "type": "bar",
                        "data": [d["awards"] for d in data][::-1],
                    },
                    {
                        "name": "高等级奖",
                        "type": "bar",
                        "data": [d["high_level_awards"] for d in data][::-1],
                    },
                ],
            }
        if kind == "level":
            data = self.by_level(flt)
            return {
                "title": {"text": "赛事级别构成", "subtext": flt.describe()},
                "tooltip": {"trigger": "item", "formatter": "{b}: {c} 项 ({d}%)"},
                "legend": {"bottom": 0},
                "series": [
                    {
                        "name": "赛事级别",
                        "type": "pie",
                        "roseType": "radius",
                        "data": [{"name": d["level"], "value": d["registrations"]} for d in data],
                    }
                ],
            }
        if kind == "workload":
            data = self.teacher_workload(flt)[:15]
            return {
                "title": {"text": "指导教师工作量折算", "subtext": flt.describe()},
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": [d["teacher"] for d in data], "axisLabel": {"rotate": 30}},
                "yAxis": {"type": "value", "name": "标准学时"},
                "series": [{"name": "折算工作量", "type": "bar", "data": [d["workload"] for d in data]}],
            }
        raise ValueError(f"暂不支持的图表类型：{kind}")

    def available_charts(self) -> list[dict[str, str]]:
        return [
            {"kind": "trend", "name": "年度趋势"},
            {"kind": "competition", "name": "赛事对比"},
            {"kind": "award_level", "name": "获奖等级构成"},
            {"kind": "major", "name": "专业分布"},
            {"kind": "teacher", "name": "教师排行"},
            {"kind": "level", "name": "赛事级别构成"},
            {"kind": "workload", "name": "教师工作量"},
        ]


# ============================================================
#  过滤与工具
# ============================================================
def _apply_filters_reg(stmt, flt: StatsFilter):
    if flt.years:
        stmt = stmt.where(Registration.year.in_(flt.years))
    if flt.competitions:
        stmt = stmt.where(Registration.competition_name.in_(flt.competitions))
    if flt.levels:
        stmt = stmt.where(Registration.competition_level.in_(flt.levels))
    if flt.categories:
        stmt = stmt.where(Registration.competition_category.in_(flt.categories))
    if flt.tracks:
        stmt = stmt.where(Registration.track_name.in_(flt.tracks))
    if flt.majors:
        conditions = [Registration.lead_major.like(f"%{m}%") for m in flt.majors]
        stmt = stmt.where(_or_(*conditions))
    if flt.teachers:
        conditions = [Registration.mentor_names.like(f"%{t}%") for t in flt.teachers]
        stmt = stmt.where(_or_(*conditions))
    if flt.students:
        conditions = [Registration.members.any(student_name_like(s)) for s in flt.students]
        stmt = stmt.where(_or_(*conditions))
    if flt.keyword:
        kw = f"%{flt.keyword}%"
        stmt = stmt.where(
            _or_(
                Registration.competition_name.like(kw),
                Registration.project_title.like(kw),
                Registration.team_name.like(kw),
            )
        )
    return stmt


def _apply_filters_award(stmt, flt: StatsFilter):
    if flt.years:
        stmt = stmt.where(Award.award_year.in_(flt.years))
    if flt.competitions:
        stmt = stmt.where(Award.competition_name.in_(flt.competitions))
    if flt.levels:
        stmt = stmt.where(Award.competition_level.in_(flt.levels))
    if flt.award_levels:
        stmt = stmt.where(Award.award_level.in_(flt.award_levels))
    if flt.majors:
        conditions = [Award.majors.like(f"%{m}%") for m in flt.majors]
        stmt = stmt.where(_or_(*conditions))
    if flt.teachers:
        conditions = [Award.mentors.like(f"%{t}%") for t in flt.teachers]
        stmt = stmt.where(_or_(*conditions))
    if flt.students:
        conditions = [Award.students.like(f"%{s}%") for s in flt.students]
        stmt = stmt.where(_or_(*conditions))
    if flt.keyword:
        kw = f"%{flt.keyword}%"
        stmt = stmt.where(_or_(Award.competition_name.like(kw), Award.project_title.like(kw)))
    return stmt


def _or_(*conditions):
    from sqlalchemy import or_

    return or_(*conditions)


def student_name_like(name: str):
    from ..db.models import RegistrationMember

    return RegistrationMember.student_name.like(f"%{name}%")


def _split_names(text: Any) -> list[str]:
    if not text:
        return []
    cleaned = str(text).replace("，", "、").replace(",", "、").replace(";", "、").replace("；", "、")
    return [x.strip() for x in cleaned.split("、") if x.strip()]


def list_competitions(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(Competition).order_by(Competition.name)).scalars()
    return [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "short_name": c.short_name,
            "level": c.level,
            "category": c.category,
            "type": c.competition_type,
            "tags": c.discipline_tags or [],
            "organizer": c.organizer,
            "official_url": c.official_url,
            "intro": c.intro,
        }
        for c in rows
    ]