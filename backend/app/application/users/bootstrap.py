"""用户相关的启动初始化用例。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.application.users.service import UserUnitOfWork
from app.core.security import hash_password
from app.domain.users.entities import UserRecord


class UserUnitOfWorkFactory(Protocol):
    def __call__(self) -> UserUnitOfWork: ...


async def ensure_default_admin(
    uow_factory: Callable[[], UserUnitOfWork],
    *,
    user_id: str,
    username: str,
    display_name: str,
    password: str,
) -> None:
    """确保系统至少存在一个可用管理员。

    启动初始化只依赖 UserRepository/UoW，不直接依赖 SQLAlchemy Model 或旧认证服务。
    """
    async with uow_factory() as uow:
        active_admins = [
            user for user in await uow.users.list_all()
            if user.is_active and user.role == "admin"
        ]
        if active_admins:
            return

        existing = await uow.users.get_by_username(username)
        if existing is not None:
            existing.display_name = display_name
            existing.password_hash = hash_password(password)
            existing.role = "admin"
            existing.is_active = True
            user = existing
        else:
            user = UserRecord(
                id=user_id,
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
        await uow.users.save(user)
        await uow.commit()
