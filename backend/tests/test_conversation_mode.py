"""会话 mode（问答模式）列测试：创建落库、按模式过滤、默认值。

使用独立临时 sqlite 文件库（pytest tmp_path），不连接真实 kb.db，
保持离线可重复，符合 tests/conftest.py 约定。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models import queries as q


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/mode_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_conversation_with_mode(session):
    conv = await q.create_conversation(
        session, "c_general", kb_id="default", title="通用会话", mode="general"
    )
    await session.commit()
    assert conv.mode == "general"


async def test_create_conversation_default_mode_is_kb(session):
    conv = await q.create_conversation(session, "c_default", title="默认会话")
    await session.commit()
    assert conv.mode == "kb"


async def test_list_conversations_filters_by_mode(session):
    await q.create_conversation(session, "c1", title="kb会话", mode="kb")
    await q.create_conversation(session, "c2", title="通用会话", mode="general")
    await session.commit()

    kb_rows = await q.list_conversations(session, mode="kb")
    gen_rows = await q.list_conversations(session, mode="general")
    assert [c.id for c in kb_rows] == ["c1"]
    assert [c.id for c in gen_rows] == ["c2"]

    all_rows = await q.list_conversations(session)
    assert len(all_rows) == 2


async def test_list_conversations_mode_plus_kb(session):
    await q.create_conversation(session, "c1", kb_id="kb_a", title="a", mode="kb")
    await q.create_conversation(session, "c2", kb_id="kb_b", title="b", mode="kb")
    await q.create_conversation(session, "c3", kb_id="kb_a", title="c", mode="general")
    await session.commit()

    rows = await q.list_conversations(session, kb_id="kb_a", mode="kb")
    assert [c.id for c in rows] == ["c1"]
