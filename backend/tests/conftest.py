"""pytest 公共夹具与路径准备。

把 backend 根目录加入 sys.path，保证在任意工作目录执行 pytest 都能 import app；
测试库统一使用 MySQL kb_test（docker 容器 kb-mysql，2026-09-13 起项目已彻底移除 SQLite）；
测试全部使用 tests/fakes.py 的替身，不连接真实 BGE-M3 / Milvus / LLM，离线可重复。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ⚠️ 测试库固定为 MySQL kb_test，与开发者本机 .env 的 DATABASE_URL 解耦。
# 原因：app.db 的 engine 在模块导入时按 DATABASE_URL 创建，若指向本机开发库会污染真实数据；
# 故此处强制指向独立测试库，并覆盖 app.db 的 engine / AsyncSessionLocal。
# pydantic-settings 中环境变量优先级高于 .env 文件，故此处设置即可生效。
_TEST_DB_URL = "mysql+asyncmy://kb:kb_user_pwd_change_me@127.0.0.1:3306/kb_test"
os.environ["DATABASE_URL"] = _TEST_DB_URL

# 替换 app.db 的 engine/session 为测试库连接串。
# 关键：用 NullPool（连接用完即断、不缓存事件循环引用），规避 asyncmy 在
# TestClient（anyio blocking portal 独立循环）与 pytest-asyncio 循环之间复用
# 连接池导致的 "AttributeError: 'NoneType' object has no attribute 'send'"。
import app.db as _db  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_db.async_engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool, future=True)
_db.AsyncSessionLocal = async_sessionmaker(
    bind=_db.async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 业务表清空顺序（子表先删，避免外键约束失败）
_TABLES = [
    "messages",
    "conversations",
    "query_logs",
    "chunks",
    "documents",
    "folders",
    "knowledge_bases",
    "users",
]


@pytest.fixture(scope="session", autouse=True)
def _test_db_schema():
    """为测试库建表（幂等）。

    测试虽以 fakes 为主，但 config 等 API 会经应用 lifespan 触碰真实库
    （create_all / ensure_default_admin），因此必须保证表和默认管理员都存在。
    这里显式初始化，而非依赖本机开发库里遗留的表与账号，
    避免测试结果受本机开发数据影响。
    """
    from app.db import create_all  # 局部导入：确保上面的环境变量与 engine 替换先生效
    from app.services.auth import ensure_default_admin

    async def _init() -> None:
        await create_all()
        # 默认管理员：受鉴权保护的接口（如 config API）依赖它登录
        await ensure_default_admin()

    asyncio.run(_init())


@pytest.fixture(autouse=True)
async def _clean_db():
    """每个用例开始前清空全部业务表并确保默认 admin 存在，结束后再清一次。

    MySQL 测试库为全部用例共享，必须让每个用例从干净状态开始，否则跨用例
    残留数据（重复主键 / 统计口径污染）会导致偶发失败；TestClient 登录类
    测试依赖 admin，故清空后先 ensure_default_admin（幂等）。
    teardown 再清一次是防御：即使用例中途崩溃，下个用例也不受影响。
    """
    from sqlalchemy import text

    from app.services.auth import ensure_default_admin

    async with _db.async_engine.begin() as conn:
        for t in _TABLES:
            await conn.execute(text(f"DELETE FROM {t}"))
    await ensure_default_admin()
    yield
    async with _db.async_engine.begin() as conn:
        for t in _TABLES:
            await conn.execute(text(f"DELETE FROM {t}"))
