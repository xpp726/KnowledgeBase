"""FastAPI 入口：只负责应用装配（中间件 / 生命周期 / 路由挂载）。

业务端点全部收敛到 app.api.api_router（统一 /api 前缀），
探测/业务逻辑在 services 层，本文件不写端点实现。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import get_settings
from app.db import create_all, ensure_schema_patches
from app.services.auth import ensure_default_admin
from app.services.document_service import ensure_default_knowledge_base
from app.services.tasks import recover_stuck_documents

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    # 启动初始化：表不存在时自动建表（幂等，SQLite 开发 / MySQL 部署均适用）。
    # 保证全新环境或 data 目录被清空时后端也能正常启动（数据丢失即视为重新初始化）。
    await create_all()
    # 启动恢复：把上次进程崩溃残留的处理中文档标记 failed，避免状态永久卡住
    await recover_stuck_documents()
    # SQLite 过渡期列迁移（幂等；MySQL 阶段走 Alembic，跳过）
    if settings.resolved_database_url.startswith("sqlite"):
        await ensure_schema_patches()
    # 确保默认 admin 存在（users 表为空时创建）
    await ensure_default_admin()
    # 确保默认知识库存在（knowledge_bases 表为空时创建，系统锚点不可删除）
    await ensure_default_knowledge_base()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"])
def root() -> dict:
    """应用元信息端点（非 /api 业务路由，保留在入口）。"""
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
    }


# 所有业务路由统一挂到 /api 前缀
app.include_router(api_router, prefix="/api")
