"""文档解析：把 PDF / Word / Excel / CSV / Markdown / TXT 统一解析为带层级的段落结构。

解析结果保留页码、表格行、章节标题等定位信息，供回答时做引用溯源。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..nlp import normalize

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".md", ".markdown", ".txt", ".json"}

# 常见中文公文层级标题
_CN_HEADING = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百]+[章节条部分]|[一二三四五六七八九十]+[、.．)）]|"
    r"（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+(?:\.\d+)*[、.．)）]?\s+\S)"
)


@dataclass
class ParsedSection:
    text: str
    title: str = ""
    page_no: int | None = None
    row_ref: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    title: str
    sections: list[ParsedSection] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.sections if s.text)

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.sections)


# ============================================================
#  各格式解析器
# ============================================================
def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="ignore")


def _split_text_into_sections(text: str, *, page_no: int | None = None) -> list[ParsedSection]:
    """按标题行/空行把长文本切成若干带标题的段落。"""
    lines = normalize(text).split("\n")
    sections: list[ParsedSection] = []
    buf: list[str] = []
    current_title = ""

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            sections.append(ParsedSection(text=body, title=current_title, page_no=page_no))
        buf = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            buf.append("")
            continue
        is_heading = bool(_CN_HEADING.match(stripped)) and len(stripped) <= 60
        if is_heading:
            flush()
            current_title = stripped
            buf.append(stripped)
        else:
            buf.append(line)
    flush()

    if not sections:
        sections = [ParsedSection(text=normalize(text), title=current_title, page_no=page_no)]
    return sections


def load_pdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    sections: list[ParsedSection] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页损坏不影响整体导入
            text = ""
        if not text.strip():
            continue
        for sec in _split_text_into_sections(text, page_no=idx):
            sec.meta["page_no"] = idx
            sections.append(sec)

    meta = {}
    try:
        info = reader.metadata or {}
        meta = {"pdf_title": str(info.get("/Title") or ""), "pages": len(reader.pages)}
    except Exception:  # noqa: BLE001
        pass
    return ParsedDocument(title=path.stem, sections=sections, meta=meta)


def load_docx(path: Path) -> ParsedDocument:
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    sections: list[ParsedSection] = []
    buf: list[str] = []
    title_path: list[str] = []
    current_title = ""

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            sections.append(ParsedSection(text=body, title=current_title))
        buf = []

    def para_is_heading(para) -> int:
        try:
            name = (para.style.name or "").lower()
        except Exception:  # noqa: BLE001
            return 0
        for lvl in (1, 2, 3, 4):
            if f"heading {lvl}" in name or name == f"标题 {lvl}" or name == f"标题{lvl}":
                return lvl
        return 0

    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        lvl = para_is_heading(para)
        if lvl or (_CN_HEADING.match(text) and len(text) <= 60):
            flush()
            depth = lvl - 1 if lvl else len(title_path)
            title_path = title_path[: max(depth, 0)]
            title_path.append(text)
            current_title = " > ".join(title_path)
            buf.append(text)
        else:
            buf.append(text)
    flush()

    for t_idx, table in enumerate(doc.tables, start=1):
        rows = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            sections.append(
                ParsedSection(
                    text=f"表格 {t_idx}\n" + "\n".join(rows),
                    title=f"{current_title} > 表格{t_idx}" if current_title else f"表格{t_idx}",
                    row_ref=f"table:{t_idx}",
                )
            )

    return ParsedDocument(title=path.stem, sections=sections, meta={"paragraphs": len(doc.paragraphs)})


def _rows_to_sections(
    rows: list[tuple[int, list[str]]], header: list[str], sheet_name: str
) -> list[ParsedSection]:
    """把表格行转成"列名：取值"的自然语言段落，便于检索与引用。"""
    sections: list[ParsedSection] = []
    header = [h.strip() or f"列{i + 1}" for i, h in enumerate(header)]
    for row_no, values in rows:
        parts = []
        for i, val in enumerate(values):
            v = (val or "").strip()
            if not v:
                continue
            key = header[i] if i < len(header) else f"列{i + 1}"
            parts.append(f"{key}：{v}")
        if not parts:
            continue
        sections.append(
            ParsedSection(
                text="；".join(parts),
                title=f"{sheet_name} 第{row_no}行",
                row_ref=f"{sheet_name}!{row_no}",
                meta={"sheet": sheet_name, "row": row_no},
            )
        )
    return sections


def load_excel(path: Path) -> ParsedDocument:
    import pandas as pd

    sheets = pd.read_excel(path, sheet_name=None, dtype=str, engine=None)
    sections: list[ParsedSection] = []
    for sheet_name, df in sheets.items():
        df = df.fillna("")
        if df.empty:
            continue
        header = [str(c) for c in df.columns.tolist()]
        rows = [(idx + 2, [str(v) for v in row]) for idx, row in enumerate(df.values.tolist())]
        sections.append(
            ParsedSection(
                text=f"工作表「{sheet_name}」共 {len(rows)} 行，字段：{'、'.join(header)}",
                title=f"{sheet_name} > 表头",
                row_ref=f"{sheet_name}!1",
                meta={"sheet": sheet_name, "kind": "header"},
            )
        )
        sections.extend(_rows_to_sections(rows, header, sheet_name))
        # 表头作为检索锚点，附带一行样例，提升"有哪些字段"这类问题的召回
    return ParsedDocument(title=path.stem, sections=sections, meta={"sheets": list(sheets.keys())})


def load_csv(path: Path) -> ParsedDocument:
    text = _read_text_file(path)
    delim = ","
    sample = text[:2000]
    if sample.count("\t") > sample.count(","):
        delim = "\t"
    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows_raw = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows_raw:
        return ParsedDocument(title=path.stem, sections=[])
    header = rows_raw[0]
    rows = [(i + 2, r) for i, r in enumerate(rows_raw[1:])]
    sections = _rows_to_sections(rows, header, path.stem)
    return ParsedDocument(title=path.stem, sections=sections, meta={"rows": len(rows)})


_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    text = text.lstrip("\ufeff")
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    try:
        import yaml

        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:  # noqa: BLE001 - 元数据格式错误不应阻断正文导入
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end() :]


def load_markdown(path: Path) -> ParsedDocument:
    meta, text = _split_front_matter(_read_text_file(path))
    lines = normalize(text).split("\n")
    sections: list[ParsedSection] = []
    buf: list[str] = []
    title_path: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            sections.append(ParsedSection(text=body, title=current))
        buf = []

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            flush()
            depth = len(m.group(1))
            title_path = title_path[: depth - 1]
            title_path.append(m.group(2).strip())
            current = " > ".join(title_path)
            buf.append(m.group(2).strip())
        else:
            buf.append(line)
    flush()
    if not sections:
        sections = _split_text_into_sections(text)
    title = str(meta.get("title") or path.stem)
    return ParsedDocument(title=title, sections=sections, meta={"front_matter": meta})


def load_json(path: Path) -> ParsedDocument:
    import json

    data = json.loads(_read_text_file(path))
    sections: list[ParsedSection] = []

    def walk(node, prefix: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]")
        else:
            sections.append(ParsedSection(text=f"{prefix}：{node}", title=prefix))

    walk(data)
    return ParsedDocument(title=path.stem, sections=sections, meta={})


_LOADERS = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".doc": load_docx,
    ".xlsx": load_excel,
    ".xls": load_excel,
    ".csv": load_csv,
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".txt": lambda p: ParsedDocument(title=p.stem, sections=_split_text_into_sections(_read_text_file(p))),
    ".json": load_json,
}


def load_document(path: str | Path) -> ParsedDocument:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    suffix = p.suffix.lower()
    loader = _LOADERS.get(suffix)
    if loader is None:
        raise ValueError(f"暂不支持的文档格式：{suffix}（支持 {'/'.join(sorted(SUPPORTED_SUFFIXES))}）")
    doc = loader(p)
    if not doc.title:
        doc.title = p.stem
    doc.meta["source_path"] = str(p)
    doc.meta["suffix"] = suffix
    return doc