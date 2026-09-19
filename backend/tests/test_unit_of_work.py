"""Unit of Work 的事务生命周期测试。"""

from __future__ import annotations

import pytest

from app.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_uow_commits_explicitly_and_closes_session():
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(session_factory=lambda: session)

    async with uow:
        assert uow.session is session
        await uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


@pytest.mark.asyncio
async def test_uow_rolls_back_when_scope_fails():
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(session_factory=lambda: session)

    with pytest.raises(RuntimeError, match="boom"):
        async with uow:
            raise RuntimeError("boom")

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_uow_rolls_back_uncommitted_scope():
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(session_factory=lambda: session)

    async with uow:
        pass

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True
