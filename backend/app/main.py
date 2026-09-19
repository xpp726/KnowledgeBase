"""FastAPI 入口：只负责应用装配（中间件 / 生命周期 / 路由挂载）。

业务端点全部收敛到 app.api.api_router（统一 /api 前缀），
探测/业务逻辑在 Application 和 Infrastructure 层，本文件不写端点实现。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.application.users.bootstrap import ensure_default_admin as ensure_default_admin_use_case
from app.config import get_settings
from app.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from app.application.documents.service import ensure_default_knowledge_base
from app.application.tasks.service import recover_stuck_documents

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    # 数据库结构由部署阶段的 `alembic upgrade head` 管理。
    # 应用启动只处理运行态恢复和业务默认数据，避免启动过程隐式改表。
    # 启动恢复：把上次进程崩溃残留的处理中文档标记 failed，避免状态永久卡住
    await recover_stuck_documents()
    # 确保默认 admin 存在（users 表为空时创建）
    await ensure_default_admin_use_case(
        SqlAlchemyUnitOfWork,
        user_id="u_admin",
        username=settings.default_admin_username,
        display_name=settings.default_admin_display_name,
        password=settings.default_admin_password,
    )
    # 确保默认知识库存在（knowledge_bases 表为空时创建，系统锚点不可删除）；
    # 同时为默认知识库建默认 folder（系统保护，不可删，可改名）。
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
