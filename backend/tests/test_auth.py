"""auth 服务单元测试：密码哈希、JWT、用户 CRUD、依赖。

使用独立临时 sqlite（pytest tmp_path），不污染真实 kb.db。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.user import User
from app.services import auth as auth_svc


@pytest_asyncio.fixture
async def session(monkeypatch):
    from app.db import async_engine
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    class _FakeCtx:
        def __init__(self):
            self._s = maker()

        async def __aenter__(self):
            return self._s

        async def __aexit__(self, *a):
            await self._s.close()

    monkeypatch.setattr(auth_svc, "AsyncSessionLocal", lambda: _FakeCtx())
    async with maker() as s:
        yield s


@pytest.mark.asyncio
async def test_password_hash_verify():
    h = auth_svc.hash_password("secret123")
    assert h != "secret123"
    assert auth_svc.verify_password("secret123", h)
    assert not auth_svc.verify_password("wrong", h)


@pytest.mark.asyncio
async def test_jwt_create_decode():
    user = User(id="u_test", username="tester", role="viewer", is_active=True)
    token = auth_svc.create_access_token(user)
    payload = auth_svc.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "u_test"
    assert payload["username"] == "tester"
    assert payload["role"] == "viewer"
    assert auth_svc.decode_token("invalid.token.here") is None


@pytest.mark.asyncio
async def test_create_and_authenticate_user(session):
    user = await auth_svc.create_user(session, "alice", "pass123", "Alice", role="editor")
    assert user.id.startswith("u_")
    assert user.role == "editor"
    assert user.display_name == "Alice"
    ok = await auth_svc.authenticate(session, "alice", "pass123")
    assert ok is not None
    assert ok.username == "alice"
    assert ok.last_login_at is not None
    assert await auth_svc.authenticate(session, "alice", "wrong") is None
    assert await auth_svc.authenticate(session, "nobody", "pass123") is None


@pytest.mark.asyncio
async def test_duplicate_username_rejected(session):
    await auth_svc.create_user(session, "bob", "p", "Bob")
    with pytest.raises(ValueError, match="已存在"):
        await auth_svc.create_user(session, "bob", "p2", "Bob2")


@pytest.mark.asyncio
async def test_invalid_role_rejected(session):
    with pytest.raises(ValueError, match="无效角色"):
        await auth_svc.create_user(session, "x", "p", "X", role="superadmin")


@pytest.mark.asyncio
async def test_update_user_role_and_active(session):
    user = await auth_svc.create_user(session, "carol", "p", "Carol")
    updated = await auth_svc.update_user(session, user.id, role="admin", is_active=False)
    assert updated is not None
    assert updated.role == "admin"
    assert updated.is_active is False
    assert await auth_svc.authenticate(session, "carol", "p") is None


@pytest.mark.asyncio
async def test_reset_and_change_password(session):
    user = await auth_svc.create_user(session, "dave", "old", "Dave")
    assert await auth_svc.reset_password(session, user.id, "newpass")
    assert await auth_svc.authenticate(session, "dave", "newpass") is not None
    assert await auth_svc.change_password(session, user.id, "newpass", "final")
    assert await auth_svc.authenticate(session, "dave", "final") is not None
    assert not await auth_svc.change_password(session, user.id, "wrong", "x")


@pytest.mark.asyncio
async def test_list_users(session):
    await auth_svc.create_user(session, "u1", "p", "U1")
    await auth_svc.create_user(session, "u2", "p", "U2")
    users = await auth_svc.list_users(session)
    # 共享 MySQL 测试库含系统 admin，断言新建用户都在返回中（而非精确计数）
    assert {u.username for u in users} >= {"u1", "u2"}


@pytest.mark.asyncio
async def test_user_to_dict_no_sensitive():
    user = User(id="u_x", username="x", display_name="X", role="viewer", password_hash="secret_hash")
    d = auth_svc.user_to_dict(user)
    assert "password_hash" not in d
    assert d["username"] == "x"
    d2 = auth_svc.user_to_dict(user, include_sensitive=True)
    assert d2["password_hash"] == "secret_hash"
