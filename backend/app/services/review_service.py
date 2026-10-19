"""项目材料初步检查：结构完整性、要素覆盖、规范性，并生成预答辩问题。

检查量表来自 data/rules/review_rubrics.yaml，可随学院评审口径调整；
检查过程不依赖大模型，结果可复核、可追溯；配置了大模型时，由工作流在其之上
追加"修改建议润色"与"针对性追问"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..nlp import normalize, split_sentences, truncate
from .policy import review_rubrics


@dataclass
class SectionResult:
    key: str
    name: str
    found: bool
    length: int = 0
    matched_heading: str = ""
    required: bool = True
    min_length: int = 0
    advice: str = ""
    excerpt: str = ""


@dataclass
class ReviewResult:
    material_type: str
    material_label: str
    score: float = 0.0
    word_count: int = 0
    sections: list[SectionResult] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    rubric: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_type": self.material_type,
            "material_label": self.material_label,
            "score": round(self.score, 1),
            "word_count": self.word_count,
            "sections": [
                {
                    "key": s.key,
                    "name": s.name,
                    "found": s.found,
                    "length": s.length,
                    "required": s.required,
                    "min_length": s.min_length,
                    "matched_heading": s.matched_heading,
                    "advice": s.advice,
                    "excerpt": s.excerpt,
                }
                for s in self.sections
            ],
            "issues": self.issues,
            "highlights": self.highlights,
            "questions": self.questions,
            "rubric": self.rubric,
            "rubric_source": "data/rules/review_rubrics.yaml",
        }


_HEADING_LINE = re.compile(r"^\s*(?:\d+[、.．)）]|[一二三四五六七八九十]+[、.．)）]|（[一二三四五六七八九十]+）|#{1,6}\s*)\s*(.{1,40})$")


class ReviewService:
    def __init__(self) -> None:
        self.cfg = review_rubrics()
        self.materials: dict[str, Any] = self.cfg.get("materials", {})
        self.general_questions: list[str] = self.cfg.get("general_questions", [])

    # ---------- 对外 ----------
    def check(
        self,
        text: str,
        material_type: str | None = None,
        *,
        competition_name: str = "",
        extra_context: str = "",
    ) -> ReviewResult:
        text = normalize(text or "")
        if not material_type or material_type not in self.materials:
            material_type = self.detect_type(text)
        rubric = self.materials.get(material_type) or {}
        blocks = _split_blocks(text)

        result = ReviewResult(
            material_type=material_type,
            material_label=str(rubric.get("label") or "项目材料"),
            word_count=len(text),
        )

        self._check_sections(rubric, blocks, text, result)
        self._check_keywords(rubric, text, result)
        self._check_compliance(rubric, text, result)
        self._build_questions(rubric, result, competition_name=competition_name)
        self._score(rubric, result)
        result.rubric = self._rubric_table(rubric, result)
        return result

    def detect_type(self, text: str) -> str:
        sample = text[:3000]
        scores: dict[str, int] = {}
        for key, rubric in self.materials.items():
            score = 0
            for section in rubric.get("sections", []):
                for heading in section.get("headings", []):
                    if heading and heading in sample:
                        score += 1
            scores[key] = score
        best = max(scores, key=lambda k: scores[k]) if scores else ""
        return best if scores.get(best, 0) > 0 else "application_form"

    def list_material_types(self) -> list[dict[str, str]]:
        return [
            {"key": k, "label": str(v.get("label") or k), "name": str(v.get("name") or k)}
            for k, v in self.materials.items()
        ]

    # ---------- 检查项 ----------
    def _check_sections(
        self, rubric: dict[str, Any], blocks: list[tuple[str, str]], full_text: str, result: ReviewResult
    ) -> None:
        for section in rubric.get("sections", []):
            headings = [str(h) for h in (section.get("headings") or [])]
            matched = ""
            body = ""
            for heading, content in blocks:
                if any(h and h in heading for h in headings):
                    matched, body = heading, content
                    break

            if not matched and headings:
                # 内容中直接提到关键词也算命中
                for h in headings:
                    idx = full_text.find(h)
                    if idx >= 0:
                        matched = h
                        body = full_text[idx : idx + 800]
                        break

            length = len(body.strip())
            required = bool(section.get("required", True))
            min_length = int(section.get("min_length") or 0)
            sr = SectionResult(
                key=str(section.get("key") or section.get("name")),
                name=str(section.get("name") or ""),
                found=bool(matched),
                length=length,
                matched_heading=matched,
                required=required,
                min_length=min_length,
                advice=str(section.get("advice") or ""),
                excerpt=truncate(body.strip().replace("\n", " "), 120),
            )
            result.sections.append(sr)

            if required and not matched:
                result.issues.append(
                    {
                        "code": f"section_missing_{sr.key}",
                        "level": "error",
                        "message": f"缺少必需章节：{sr.name}",
                        "suggestion": sr.advice or f"补充「{sr.name}」部分，这是评委重点关注的内容",
                    }
                )
            elif matched and min_length and length < min_length:
                result.issues.append(
                    {
                        "code": f"section_short_{sr.key}",
                        "level": "warning",
                        "message": f"「{sr.name}」篇幅偏少（{length} 字，建议不少于 {min_length} 字）",
                        "suggestion": sr.advice,
                    }
                )
            elif matched:
                result.highlights.append(f"已包含「{sr.name}」（约 {length} 字）")

    def _check_keywords(self, rubric: dict[str, Any], text: str, result: ReviewResult) -> None:
        for group in rubric.get("keyword_groups", []):
            words = [str(w) for w in (group.get("words") or [])]
            hits = [w for w in words if w and w in text]
            name = str(group.get("group") or "")
            if not hits:
                key = _group_key(name)
                result.issues.append(
                    {
                        "code": f"keyword_missing_{key}",
                        "level": "warning" if key in {"innovation", "feasible", "metric"} else "info",
                        "message": f"「{name}」要素不明显（未出现 {'/'.join(words[:5])} 等表述）",
                        "suggestion": str(group.get("advice") or ""),
                    }
                )
            else:
                result.highlights.append(f"「{name}」已覆盖：{'、'.join(hits[:5])}")

    def _check_compliance(self, rubric: dict[str, Any], text: str, result: ReviewResult) -> None:
        compliance = rubric.get("compliance") or {}

        for word in compliance.get("placeholder_words") or []:
            if word and word in text:
                count = text.count(word)
                result.issues.append(
                    {
                        "code": f"placeholder_{word}",
                        "level": "error",
                        "message": f"存在未完成的占位内容「{word}」（{count} 处）",
                        "suggestion": "提交前务必补全所有占位内容，评委对未完成材料非常敏感",
                    }
                )

        if compliance.get("anonymize_required"):
            patterns = [str(p) for p in (compliance.get("anonymize_patterns") or [])]
            limit = int(compliance.get("max_school_mentions", 1) or 1)
            hits: list[str] = []
            for p in patterns:
                if not p:
                    continue
                cnt = text.count(p)
                if cnt:
                    hits.append(f"{p}×{cnt}")
            total_hits = sum(int(h.split("×")[1]) for h in hits) if hits else 0
            if total_hits > limit:
                result.issues.append(
                    {
                        "code": "anonymize_violation",
                        "level": "warning",
                        "message": f"材料中出现可能暴露学校/教师身份的信息：{'、'.join(hits)}",
                        "suggestion": "多数赛事要求评审材料匿名（不得出现学校名、校徽、教师姓名），请用「某高校」「指导教师」等中性表述替换",
                    }
                )

        paragraphs = [p for p in text.split("\n") if len(p.strip()) > 30]
        if paragraphs and max(len(p) for p in paragraphs) > 1500:
            result.issues.append(
                {
                    "code": "paragraph_too_long",
                    "level": "info",
                    "message": "存在超过 1500 字的超长段落，可读性较差",
                    "suggestion": "拆分为多个小节，使用小标题、项目符号或表格提升可读性",
                }
            )

        if not re.search(r"\d", text):
            result.issues.append(
                {
                    "code": "no_number",
                    "level": "warning",
                    "message": "全文未出现任何数字，缺乏量化描述",
                    "suggestion": "补充量化指标（性能数据、实验规模、预期指标等），增强说服力",
                }
            )

        if len(text) < 500:
            result.issues.append(
                {
                    "code": "too_short",
                    "level": "error",
                    "message": f"材料总篇幅仅 {len(text)} 字，明显不足以支撑评审",
                    "suggestion": "按量表逐节补充内容，建议参考往年获奖作品的结构与详略程度",
                }
            )

    # ---------- 问题与评分 ----------
    def _build_questions(
        self, rubric: dict[str, Any], result: ReviewResult, *, competition_name: str = ""
    ) -> None:
        qmap: dict[str, str] = rubric.get("questions") or {}
        asked: set[str] = set()

        for issue in result.issues:
            code = issue["code"]
            for key in ("innovation", "feasible", "metric", "outcome", "team", "budget"):
                if code.endswith(key) or f"_{key}" in code:
                    q = qmap.get(f"{key}_missing")
                    if q and q not in asked:
                        asked.add(q)
                        result.questions.append(q)

        missing_sections = [s for s in result.sections if not s.found and s.required]
        for s in missing_sections:
            q = f"材料中「{s.name}」部分较为简略或缺失，请说明你是如何考虑这一部分的？"
            if q not in asked:
                asked.add(q)
                result.questions.append(q)

        for q in self.general_questions:
            if len(result.questions) >= 8:
                break
            if q not in asked:
                asked.add(q)
                result.questions.append(q)

        if competition_name:
            result.questions.insert(0, f"请用一句话说明这个项目为什么适合参加{competition_name}，评委为什么应当选择你们？")

    def _score(self, rubric: dict[str, Any], result: ReviewResult) -> None:
        errors = sum(1 for i in result.issues if i["level"] == "error")
        warnings = sum(1 for i in result.issues if i["level"] == "warning")
        infos = sum(1 for i in result.issues if i["level"] == "info")

        required_sections = [s for s in result.sections if s.required]
        structure_ratio = (
            sum(1 for s in required_sections if s.found) / len(required_sections) if required_sections else 1.0
        )
        depth_ratio = 1.0
        if required_sections:
            depth_ratio = sum(
                min(1.0, s.length / s.min_length) if s.min_length else 1.0 for s in required_sections
            ) / len(required_sections)

        base = 40 * structure_ratio + 35 * depth_ratio + 25 * max(0.0, 1 - 0.12 * warnings - 0.25 * errors)
        result.score = float(max(0.0, min(100.0, base - infos * 1.5)))

    def _rubric_table(self, rubric: dict[str, Any], result: ReviewResult) -> list[dict[str, Any]]:
        by_key = {s.key: s for s in result.sections}
        table = []
        for section in rubric.get("sections", []):
            key = str(section.get("key") or section.get("name"))
            sr = by_key.get(key)
            table.append(
                {
                    "检查项": str(section.get("name")),
                    "是否必需": "必需" if section.get("required", True) else "建议",
                    "材料情况": (
                        f"已包含（约 {sr.length} 字）" if sr and sr.found else ("缺失" if sr else "未检查")
                    ),
                    "建议篇幅": f"不少于 {section.get('min_length')} 字" if section.get("min_length") else "—",
                    "改进建议": str(section.get("advice") or ""),
                }
            )
        return table


def _split_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    heading = "开头"
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            blocks.append((heading, body))
        buf = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            buf.append("")
            continue
        m = _HEADING_LINE.match(stripped)
        is_heading = bool(m) and len(stripped) <= 40
        if is_heading:
            flush()
            heading = stripped
        else:
            buf.append(line)
    flush()

    if not blocks:
        blocks = [("全文", text)]
    return blocks


def _group_key(name: str) -> str:
    mapping = {
        "创新性表述": "innovation",
        "可行性论证": "feasible",
        "量化指标": "metric",
        "推广价值": "outcome",
        "技术细节": "feasible",
        "数据与实验": "metric",
        "工程规范": "outcome",
        "结果呈现": "metric",
    }
    return mapping.get(name, "other")


def build_review_summary(result: ReviewResult) -> str:
    """把检查结果整理为一段可直接展示/导出的总结文字。"""
    lines = [
        f"材料类型：{result.material_label}",
        f"总篇幅：{result.word_count} 字",
        f"初步评分：{result.score:.1f} / 100",
        "",
        "【结构检查】",
    ]
    for s in result.sections:
        flag = "✓" if s.found else ("✗" if s.required else "○")
        lines.append(f"{flag} {s.name}：{('约 ' + str(s.length) + ' 字') if s.found else '未找到对应章节'}")
    if result.issues:
        lines += ["", "【问题与建议】"]
        for i, issue in enumerate(result.issues, start=1):
            lines.append(f"{i}. [{issue['level']}] {issue['message']}")
            if issue.get("suggestion"):
                lines.append(f"   建议：{issue['suggestion']}")
    if result.highlights:
        lines += ["", "【做得好的地方】"]
        lines += [f"· {h}" for h in result.highlights[:8]]
    if result.questions:
        lines += ["", "【预答辩问题】"]
        lines += [f"{i}. {q}" for i, q in enumerate(result.questions, start=1)]
    return "\n".join(lines)


def guess_sentences(text: str, limit: int = 5) -> list[str]:
    return split_sentences(text)[:limit]