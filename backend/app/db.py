"""数据访问层（SQLAlchemy 2.0 async，仅 MySQL）。

2026-09-13：清理全部 legacy 裸 sqlite3 层（SCHEMA / _connect / get_conn / init_db
及文档、分块、统计同步函数），项目不再使用 SQLite，统一走 ORM（models/queries）。
schema 演进以 Alembic 为准，启动时 create_all / ensure_schema_patches 兜底幂等建表与补列。

向量与相似度检索全部交给 Milvus，本层只存结构化元数据和 chunk 原文。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# create_async_engine 是懒连接，模块级创建无副作用；方言由 database_url 决定（仅 MySQL）
async_engine = create_async_engine(
    settings.resolved_database_url,
    echo=settings.db_echo,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用的 async session，自动 commit/rollback。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """开发期便捷建表（CREATE TABLE IF NOT EXISTS 语义，不影响已存在的表）。

    生产环境 schema 演进一律走 Alembic（alembic upgrade head），本函数仅供
    CLI 脚本开箱即用与测试，不处理列变更。
    """
    from app.models import Base  # 局部导入避免循环依赖

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_schema_patches() -> None:
    """轻量列迁移（幂等，每次启动执行，仅 MySQL）。

    表不存在时跳过（create_all 会建新表）。
    """
    from sqlalchemy import text

    patches = [
        (
            "conversations", "mode",
            "ALTER TABLE conversations ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'kb'",
        ),
        (
            "query_logs", "mode",
            "ALTER TABLE query_logs ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'kb'",
        ),
        (
            "conversations", "user_id",
            "ALTER TABLE conversations ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT ''",
        ),
        (
            "query_logs", "user_id",
            "ALTER TABLE query_logs ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT ''",
        ),
        (
            "documents", "kb_id",
            "ALTER TABLE documents ADD COLUMN kb_id VARCHAR(64) NOT NULL DEFAULT 'default'",
        ),
        (
            "documents", "folder_id",
            "ALTER TABLE documents ADD COLUMN folder_id VARCHAR(32)",
        ),
    ]
    async with async_engine.begin() as conn:
        for table, column, alter_sql in patches:
            if await _column_exists(conn, table, column):
                continue
            await conn.execute(text(alter_sql))
            logger.info("迁移：%s 增加 %s 列", table, column)


async def _column_exists(conn, table: str, column: str) -> bool:
    """MySQL：通过 information_schema.columns 检测列是否存在。"""
    from sqlalchemy import text

    sql = text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
    )
    rows = await conn.execute(sql, {"t": table, "c": column})
    return rows.fetchone() is not None
