"""用户启动初始化用例测试。"""

from __future__ import annotations

import pytest

from app.application.users.bootstrap import ensure_default_admin
from app.core.security import verify_password
from app.domain.users.entities import UserRecord


class FakeUsers:
    def __init__(self):
        self.items: dict[str, UserRecord] = {}

    async def get_by_username(self, username):
        return next((user for user in self.items.values() if user.username == username), None)

    async def list_all(self):
        return list(self.items.values())

    async def save(self, user):
        self.items[user.id] = user
        return user


class FakeUow:
    def __init__(self):
        self.users = FakeUsers()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


@pytest.mark.asyncio
async def test_ensure_default_admin_creates_admin_through_uow():
    uow = FakeUow()

    await ensure_default_admin(
        lambda: uow,
        user_id="u_admin",
        username="admin",
        display_name="Administrator",
        password="secret123",
    )

    user = uow.users.items["u_admin"]
    assert user.role == "admin"
    assert user.is_active is True
    assert verify_password("secret123", user.password_hash)
    assert uow.commit_count == 1


@pytest.mark.asyncio
async def test_ensure_default_admin_is_idempotent_for_active_admin():
    uow = FakeUow()
    existing = UserRecord(
        id="u_admin",
        username="admin",
        display_name="Administrator",
        password_hash="already-hashed",
        role="admin",
        is_active=True,
    )
    uow.users.items[existing.id] = existing

    await ensure_default_admin(
        lambda: uow,
        user_id="u_admin",
        username="admin",
        display_name="Administrator",
        password="secret123",
    )

    assert uow.users.items[existing.id] is existing
    assert uow.commit_count == 0


@pytest.mark.asyncio
async def test_ensure_default_admin_keeps_another_active_admin():
    uow = FakeUow()
    existing = UserRecord(
        id="u_other",
        username="owner",
        display_name="Owner",
        password_hash="already-hashed",
        role="admin",
        is_active=True,
    )
    uow.users.items[existing.id] = existing

    await ensure_default_admin(
        lambda: uow,
        user_id="u_admin",
        username="admin",
        display_name="Administrator",
        password="secret123",
    )

    assert list(uow.users.items) == ["u_other"]
    assert uow.commit_count == 0
