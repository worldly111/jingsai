"""统计分析与结果导出接口。"""

from __future__ import annotations

import io
from typing import Any
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..services.export_service import ExportService, to_csv_bytes, to_docx_bytes, to_excel_bytes
from ..services.stats_service import StatsFilter, StatsService
from ..security import require

router = APIRouter()

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _flt(
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "",
) -> StatsFilter:
    def split(raw: str) -> list[str]:
        return [x.strip() for x in (raw or "").replace("，", ",").split(",") if x.strip()]

    try:
        year_list = [int(y) for y in split(years)]
    except ValueError as exc:
        raise HTTPException(400, "years 参数应为逗号分隔的年份") from exc
    return StatsFilter(
        years=year_list, competitions=split(competitions), levels=split(levels),
        categories=split(categories), award_levels=split(award_levels), majors=split(majors),
        teachers=split(teachers), students=split(students), tracks=split(tracks), keyword=keyword,
    )


def _download(name: str, data: bytes, media: str) -> Response:
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    })


DIMENSIONS = {
    "year": ("年度", "by_year"),
    "competition": ("赛事", "by_competition"),
    "major": ("专业", "by_major"),
    "award_level": ("获奖等级", "by_award_level"),
    "level": ("赛事级别", "by_level"),
    "teacher": ("指导教师", "by_teacher"),
    "student": ("学生", "by_student"),
    "workload": ("教师工作量", "teacher_workload"),
}


@router.get("/stats/overview", dependencies=[Depends(require("stats.view"))])
def overview(
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", db: Session = Depends(get_db),
) -> dict[str, Any]:
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    svc = StatsService(db)
    return {
        "filter": flt.to_dict(),
        "filter_text": flt.describe(),
        "overview": svc.overview(flt),
        "by_year": svc.by_year(flt),
        "by_competition": svc.by_competition(flt),
        "by_major": svc.by_major(flt),
        "by_award_level": svc.by_award_level(flt),
        "by_level": svc.by_level(flt),
        "by_teacher": svc.by_teacher(flt),
        "by_student": svc.by_student(flt),
        "teacher_workload": svc.teacher_workload(flt),
        "year_major_awards": svc.year_major_awards(flt),
        "data_source": "registrations / awards / registration_members / registration_mentors 结构化台账",
    }


@router.get("/stats/dimensions/{dimension}", dependencies=[Depends(require("stats.view"))])
def dimension(
    dimension: str,
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", db: Session = Depends(get_db),
) -> dict[str, Any]:
    if dimension not in DIMENSIONS:
        raise HTTPException(404, f"不支持的分析维度：{dimension}，可选：{list(DIMENSIONS)}")
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    label, method = DIMENSIONS[dimension]
    rows = getattr(StatsService(db), method)(flt)
    return {"dimension": dimension, "label": label, "filter_text": flt.describe(), "rows": rows}


@router.get("/stats/charts", dependencies=[Depends(require("stats.view"))])
def charts() -> dict[str, Any]:
    svc = StatsService(None)  # 图表目录不查询数据库
    return {"items": svc.available_charts()}


@router.get("/stats/chart/{kind}", dependencies=[Depends(require("stats.view"))])
def chart(
    kind: str,
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", db: Session = Depends(get_db),
) -> dict[str, Any]:
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    try:
        return StatsService(db).chart(kind, flt)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class StatsExportRequest(BaseModel):
    years: list[int] = Field(default_factory=list)
    competitions: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    award_levels: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    teachers: list[str] = Field(default_factory=list)
    students: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    keyword: str = ""


def _flt_from_body(body: StatsExportRequest) -> StatsFilter:
    return StatsFilter(
        years=body.years, competitions=body.competitions, levels=body.levels,
        categories=body.categories, award_levels=body.award_levels, majors=body.majors,
        teachers=body.teachers, students=body.students, tracks=body.tracks, keyword=body.keyword,
    )


@router.get("/export/stats", dependencies=[Depends(require("export.use"))])
def export_stats(
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", format: str = "xlsx", db: Session = Depends(get_db),
) -> Response:
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    svc = ExportService(db)
    if format == "csv":
        data = svc.build_stats_sheets(flt)
        buf = io.BytesIO()
        for name, df in data.items():
            buf.write(f"\n# {name}\n".encode("utf-8"))
            buf.write(to_csv_bytes(df))
        return _download("竞赛统计报表.csv", buf.getvalue(), "text/csv; charset=utf-8")
    name, content = svc.stats_excel(flt)
    return _download(name, content, XLSX)


@router.get("/export/awards", dependencies=[Depends(require("export.use"))])
def export_awards(
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", db: Session = Depends(get_db),
) -> Response:
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    name, content = ExportService(db).awards_excel(flt)
    return _download(name, content, XLSX)


@router.get("/export/registrations", dependencies=[Depends(require("export.use"))])
def export_registrations(
    years: str = "", competitions: str = "", levels: str = "", categories: str = "",
    award_levels: str = "", majors: str = "", teachers: str = "", students: str = "",
    tracks: str = "", keyword: str = "", db: Session = Depends(get_db),
) -> Response:
    flt = _flt(years, competitions, levels, categories, award_levels, majors, teachers, students, tracks, keyword)
    name, content = ExportService(db).registrations_excel(flt)
    return _download(name, content, XLSX)


class AgentExportRequest(BaseModel):
    title: str = "智能体结果"
    answer: str = ""
    tables: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/export/agent", dependencies=[Depends(require("export.result"))])
def export_agent_result(body: AgentExportRequest, format: str = "docx") -> Response:
    title = body.title.strip() or "智能体结果"
    if format == "md":
        lines = [f"# {title}", "", body.answer]
        for table in body.tables:
            lines += ["", f"## {table.get('title') or '表格'}", ""]
            cols = table.get("columns") or []
            rows = table.get("rows") or []
            if cols:
                header = " | ".join(str(c.get("label") or c.get("key") or c) for c in cols)
                lines += [f"| {header} |", "| " + " | ".join("---" for _ in cols) + " |"]
                for row in rows:
                    lines.append("| " + " | ".join(str(row.get(c.get("key") or c, "")) for c in cols) + " |")
        data = ("\ufeff" + "\n".join(lines)).encode("utf-8")
        return _download(f"{title}.md", data, "text/markdown; charset=utf-8")

    frames: list[tuple[str, pd.DataFrame]] = []
    for table in body.tables:
        cols = table.get("columns") or []
        rows = table.get("rows") or []
        if not cols:
            continue
        df = pd.DataFrame([
            {str(c.get("label") or c.get("key") or c): row.get(c.get("key") or c, "") for c in cols}
            for row in rows
        ])
        frames.append((str(table.get("title") or "表格"), df))
    content = to_docx_bytes(title, body.answer, frames)
    return _download(f"{title}.docx", content, DOCX)


class TableExportRequest(BaseModel):
    title: str = "数据表"
    columns: list[dict[str, Any]] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    format: str = "xlsx"


@router.post("/export/table", dependencies=[Depends(require("export.use"))])
def export_table(body: TableExportRequest) -> Response:
    if not body.columns:
        raise HTTPException(400, "缺少列定义")
    df = pd.DataFrame([
        {str(c.get("label") or c.get("key") or c): row.get(c.get("key") or c, "") for c in body.columns}
        for row in body.rows
    ])
    if body.format == "csv":
        return _download(f"{body.title}.csv", to_csv_bytes(df), "text/csv; charset=utf-8")
    return _download(f"{body.title}.xlsx", to_excel_bytes({body.title: df}), XLSX)
