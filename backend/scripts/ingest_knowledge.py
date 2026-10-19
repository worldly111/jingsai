"""导入知识库文档（PDF / Word / Excel / Markdown / TXT / CSV）。

支持从 Markdown 文件的 YAML front matter 读取标题、文号、年份、赛事、来源等元数据：
    ---
    title: 关于……的通知
    doc_type: 通知公告
    year: 2026
    competition_name: 全国大学生数学建模竞赛
    issuing_body: ……
    doc_no: ……
    source_url: ……
    tags: [……]
    ---

用法：
    python scripts/ingest_knowledge.py                 # 导入 data/knowledge 全部文件
    python scripts/ingest_knowledge.py --file 某通知.md
    python scripts/ingest_knowledge.py --dir ./data/uploads --no-replace
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.rag.ingest import ingest_directory, ingest_file  # noqa: E402
from app.rag.vectorstore import KnowledgeIndex  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入竞赛知识库文档")
    parser.add_argument("--dir", default=str(settings.knowledge_path), help="待导入目录")
    parser.add_argument("--file", action="append", default=[], help="指定文件（可重复）")
    parser.add_argument("--no-replace", action="store_true", help="相同内容已存在时跳过，不重新导入")
    parser.add_argument("--no-init", action="store_true", help="跳过建表检查")
    args = parser.parse_args()

    if not args.no_init:
        init_db()

    results = []
    with session_scope() as db:
        if args.file:
            for raw in args.file:
                p = Path(raw)
                if not p.is_absolute():
                    p = (ROOT / p).resolve()
                results.append(ingest_file(db, p, replace_existing=not args.no_replace))
        else:
            results = ingest_directory(db, args.dir)

    if not results:
        print(f"未找到可导入的文件：{args.dir}")
        return 1

    print(f"{'状态':<6}{'分块':>5}{'字符':>8}  文档")
    print("-" * 88)
    for r in results:
        print(f"{r.status:<6}{r.chunk_count:>5}{r.char_count:>8}  {r.title}")
        if r.message:
            print(f"      说明：{r.message}")
    ok = sum(1 for r in results if r.status == "已入库")
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if r.status == "失败")
    print("-" * 88)
    print(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}，总分块 {sum(r.chunk_count for r in results)}")

    with session_scope() as db:
        KnowledgeIndex.instance().ensure_loaded(db, force=True)
        stats = KnowledgeIndex.instance().stats()
    print(f"检索索引：{stats}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
