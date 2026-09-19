"""新 Application Service 层的隔离测试。

这些测试不连接数据库，验证业务层只依赖 Repository/UoW 接口，后续迁移其他
业务模块时可以沿用同样的测试方式。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.application.stats.service import StatsApplicationService
from app.application.users.service import UserApplicationService
from app.domain.users.entities import UserRecord


class FakeUserRepository:
    def __init__(self):
        self.items: dict[str, UserRecord] = {}

    async def get_by_username(self, username: str):
        return next((item for item in self.items.values() if item.username == username), None)

    async def get_by_id(self, user_id: str):
        return self.items.get(user_id)

    async def list_all(self):
        return list(self.items.values())

    async def save(self, user: UserRecord):
        if user.created_at is None:
            user.created_at = datetime.now()
        user.updated_at = datetime.now()
        self.items[user.id] = user
        return user


class FakeUserUnitOfWork:
    def __init__(self):
        self.users = FakeUserRepository()
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1


class FakeStatsRepository:
    def __init__(self):
        self.calls: list[tuple[int | None, str]] = []

    async def summary(self, *, days=None, mode="all"):
        self.calls.append((days, mode))
        return {"cards": {"total": 0}, "trend": [], "top_questions": [], "top_docs": [], "kb_dist": []}


@pytest.mark.asyncio
async def test_user_application_service_uses_repository_and_uow():
    uow = FakeUserUnitOfWork()
    service = UserApplicationService(uow)

    user = await service.create_user(
        username="alice",
        password="secret123",
        display_name="Alice",
        role="editor",
    )

    assert user.username == "alice"
    assert uow.commit_count == 1
    assert (await service.authenticate("alice", "secret123")).id == user.id
    assert await service.authenticate("alice", "wrong") is None
    assert uow.commit_count == 2


@pytest.mark.asyncio
async def test_user_application_service_keeps_admin_self_protection():
    uow = FakeUserUnitOfWork()
    service = UserApplicationService(uow)
    user = await service.create_user(
        username="admin",
        password="secret123",
        display_name="Admin",
        role="admin",
    )

    with pytest.raises(ValueError, match="不能禁用"):
        await service.update_user(user.id, actor_id=user.id, is_active=False)
    with pytest.raises(ValueError, match="不能降低"):
        await service.update_user(user.id, actor_id=user.id, role="viewer")


@pytest.mark.asyncio
async def test_stats_application_service_normalizes_mode_at_boundary():
    repository = FakeStatsRepository()
    service = StatsApplicationService(repository)

    await service.summary(days=7, mode="invalid")

    assert repository.calls == [(7, "kb")]
