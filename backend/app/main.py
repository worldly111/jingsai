"""FastAPI 应用入口。

本地运行：
    uvicorn app.main:app --reload --port 8000
生产运行：
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import competitions, core, finance, knowledge, llm_chat, stats
from .config import BACKEND_DIR, settings
from .db.base import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("competition-agent")

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    init_db()
    logger.info("应用启动：%s（数据库 %s）", settings.app_name, settings.database_url)
    yield
    logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    description="面向学院竞赛管理、教师指导和学生备赛的一体化智能体服务。",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for router in (
    core.router,
    knowledge.router,
    competitions.router,
    finance.router,
    stats.router,
    llm_chat.router,
):
    app.include_router(router, prefix="/api")

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """托管构建后的 Vue 前端；开发模式下由 Vite 提供页面。"""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": "后端已启动。前端开发服务器：http://127.0.0.1:5173；接口文档：/api/docs",
        "frontend_built": False,
    }
