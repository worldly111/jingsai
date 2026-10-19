"""创建数据库表结构。

用法：
    python scripts/init_db.py               # 创建缺失的表（可重复执行）
    python scripts/init_db.py --reset       # 删除全部表后重建（会清空数据！）
    python scripts/init_db.py --seed        # 建表后执行种子数据导入
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.db.base import Base  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化竞赛辅助服务数据库")
    parser.add_argument("--reset", action="store_true", help="删除全部表并重建，会清空现有数据")
    parser.add_argument("--seed", action="store_true", help="建表后导入种子数据")
    args = parser.parse_args()

    settings.ensure_dirs()
    print(f"数据库：{settings.database_url}")

    if args.reset:
        from app.db import models  # noqa: F401

        confirm = input("--reset 会删除全部表与数据，输入 RESET 确认：").strip()
        if confirm != "RESET":
            print("已取消。")
            return 1
        Base.metadata.drop_all(bind=engine)
        print("已删除全部表。")

    init_db()
    tables = sorted(Base.metadata.tables)
    print(f"建表完成，共 {len(tables)} 张：")
    for name in tables:
        print(f"  - {name}")

    if args.seed:
        print("\n开始导入种子数据……")
        from seed_data import seed_all

        summary = seed_all()
        for key, value in summary.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
