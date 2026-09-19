"""用户管理用例。

该服务只依赖用户 Repository 和 Unit of Work 协议，不依赖 FastAPI 或
SQLAlchemy。当前返回 ``UserRecord``，由 API 层统一序列化。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol

from app.core.security import hash_password, verify_password
from app.domain.users.entities import UserRecord
from app.domain.users.repositories import UserRepository

ROLES = ("admin", "editor", "viewer")


class UserUnitOfWork(Protocol):
    users: UserRepository

    async def commit(self) -> None: ...


class UserApplicationService:
    def __init__(self, uow: UserUnitOfWork):
        self._uow = uow

    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        user = await self._uow.users.get_by_username(username)
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            return None
        user.last_login_at = datetime.now()
        await self._uow.users.save(user)
        await self._uow.commit()
        return user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return await self._uow.users.get_by_id(user_id)

    async def list_users(self) -> list[UserRecord]:
        return await self._uow.users.list_all()

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str = "viewer",
    ) -> UserRecord:
        if role not in ROLES:
            raise ValueError(f"无效角色: {role}")
        if await self._uow.users.get_by_username(username):
            raise ValueError(f"用户名已存在: {username}")
        user = UserRecord(
            id=f"u_{int(time.time() * 1000)}",
            username=username,
            display_name=display_name or username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        user = await self._uow.users.save(user)
        await self._uow.commit()
        return user

    async def update_user(
        self,
        user_id: str,
        *,
        actor_id: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        display_name: str | None = None,
        reset_password: str | None = None,
    ) -> UserRecord | None:
        user = await self._uow.users.get_by_id(user_id)
        if user is None:
            return None
        if actor_id == user_id and is_active is False:
            raise ValueError("不能禁用当前登录账号")
        if actor_id == user_id and role is not None and role != "admin":
            raise ValueError("不能降低自己的管理员角色")
        if role is not None:
            if role not in ROLES:
                raise ValueError(f"无效角色: {role}")
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if display_name is not None:
            user.display_name = display_name
        if reset_password:
            if len(reset_password) < 6:
                raise ValueError("重置密码长度不能少于 6 位")
            user.password_hash = hash_password(reset_password)
        user = await self._uow.users.save(user)
        await self._uow.commit()
        return user

    async def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
    ) -> bool:
        user = await self._uow.users.get_by_id(user_id)
        if user is None or not verify_password(old_password, user.password_hash):
            return False
        user.password_hash = hash_password(new_password)
        await self._uow.users.save(user)
        await self._uow.commit()
        return True


def user_to_dict(user: UserRecord, include_sensitive: bool = False) -> dict:
    """把领域用户记录转换成 API 公开结构。"""
    result = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "last_login_at": user.last_login_at,
    }
    if include_sensitive:
        result["password_hash"] = user.password_hash
    return result
