"""数据库引擎与会话管理。

默认使用 SQLite（开箱即用）；将 DATABASE_URL 换成 mysql+pymysql:// 或
postgresql+psycopg:// 即可切换到学院自有的 MySQL / PostgreSQL，业务代码无需改动。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import settings


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    url = settings.database_url
    kwargs: dict = {"echo": settings.sql_echo, "pool_pre_ping": True, "future": True}

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            # 保证相对路径中的目录存在
            db_file = url.replace("sqlite:///", "", 1)
            (settings.data_path / db_file.split("/")[-1]).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_recycle"] = 3600

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragma(dbapi_conn, _record):  # pragma: no cover - 驱动层回调
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入用的会话工厂。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """脚本 / 工作流中使用的会话上下文。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)