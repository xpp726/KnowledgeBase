"""认证安全组件与用户应用服务测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.application.users.service import UserApplicationService, user_to_dict
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.domain.users.entities import UserRecord


class FakeUserRepository:
    def __init__(self):
        self.items: dict[str, UserRecord] = {}

    async def get_by_username(self, username: str):
        return next(
            (user for user in self.items.values() if user.username == username),
            None,
        )

    async def get_by_id(self, user_id: str):
        return self.items.get(user_id)

    async def list_all(self):
        return list(self.items.values())

    async def save(self, user: UserRecord):
        now = datetime.now()
        user.created_at = user.created_at or now
        user.updated_at = now
        self.items[user.id] = user
        return user


class FakeUserUnitOfWork:
    def __init__(self):
        self.users = FakeUserRepository()
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1


def _service() -> tuple[UserApplicationService, FakeUserUnitOfWork]:
    uow = FakeUserUnitOfWork()
    return UserApplicationService(uow), uow


def test_password_hash_verify():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_create_decode():
    user = UserRecord(
        id="u_test",
        username="tester",
        display_name="Tester",
        password_hash="unused",
        role="viewer",
        is_active=True,
    )
    token = create_access_token(user)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "u_test"
    assert payload["username"] == "tester"
    assert payload["role"] == "viewer"
    assert decode_access_token("invalid.token.here") is None


@pytest.mark.asyncio
async def test_create_and_authenticate_user():
    service, uow = _service()
    user = await service.create_user(
        username="alice",
        password="pass123",
        display_name="Alice",
        role="editor",
    )
    assert user.id.startswith("u_")
    assert user.role == "editor"
    assert user.display_name == "Alice"
    ok = await service.authenticate("alice", "pass123")
    assert ok is not None
    assert ok.username == "alice"
    assert ok.last_login_at is not None
    assert await service.authenticate("alice", "wrong") is None
    assert await service.authenticate("nobody", "pass123") is None
    assert uow.commit_count == 2


@pytest.mark.asyncio
async def test_duplicate_username_rejected():
    service, _ = _service()
    await service.create_user(username="bob", password="pass123", display_name="Bob")
    with pytest.raises(ValueError, match="已存在"):
        await service.create_user(
            username="bob", password="pass456", display_name="Bob 2"
        )


@pytest.mark.asyncio
async def test_invalid_role_rejected():
    service, _ = _service()
    with pytest.raises(ValueError, match="无效角色"):
        await service.create_user(
            username="x", password="pass123", display_name="X", role="superadmin"
        )


@pytest.mark.asyncio
async def test_update_user_role_and_active():
    service, _ = _service()
    user = await service.create_user(
        username="carol", password="pass123", display_name="Carol"
    )
    updated = await service.update_user(user.id, role="admin", is_active=False)
    assert updated is not None
    assert updated.role == "admin"
    assert updated.is_active is False
    assert await service.authenticate("carol", "pass123") is None


@pytest.mark.asyncio
async def test_reset_and_change_password():
    service, _ = _service()
    user = await service.create_user(
        username="dave", password="oldpass", display_name="Dave"
    )
    assert await service.update_user(user.id, reset_password="newpass")
    assert await service.authenticate("dave", "newpass") is not None
    assert await service.change_password(user.id, "newpass", "finalpass")
    assert await service.authenticate("dave", "finalpass") is not None
    assert not await service.change_password(user.id, "wrong", "another")


@pytest.mark.asyncio
async def test_list_users():
    service, _ = _service()
    await service.create_user(username="u1", password="pass123", display_name="U1")
    await service.create_user(username="u2", password="pass123", display_name="U2")
    users = await service.list_users()
    assert {user.username for user in users} == {"u1", "u2"}


@pytest.mark.asyncio
async def test_user_to_dict_no_sensitive():
    user = UserRecord(
        id="u_x",
        username="x",
        display_name="X",
        password_hash="secret_hash",
        role="viewer",
        is_active=True,
    )
    result = user_to_dict(user)
    assert "password_hash" not in result
    assert result["username"] == "x"
    result_with_sensitive = user_to_dict(user, include_sensitive=True)
    assert result_with_sensitive["password_hash"] == "secret_hash"
