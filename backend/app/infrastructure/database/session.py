"""SQLAlchemy engine、session 生命周期和开发期 schema 初始化。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

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


def get_session_factory():
    return AsyncSessionLocal


def get_engine():
    return async_engine


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """短事务 session：正常退出提交，异常退出回滚。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """开发/测试期幂等建表；生产环境必须使用 Alembic。"""
    from app.infrastructure.database.models import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
