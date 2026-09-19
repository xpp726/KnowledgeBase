"""用户 Repository 的 SQLAlchemy 实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.users.entities import UserRecord
from app.domain.users.repositories import UserRepository
from app.infrastructure.database.models.user import User


def _to_record(user: User) -> UserRecord:
    return UserRecord(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        password_hash=user.password_hash,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_username(self, username: str) -> UserRecord | None:
        result = await self._session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        return _to_record(user) if user else None

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        user = await self._session.get(User, user_id)
        return _to_record(user) if user else None

    async def list_all(self) -> list[UserRecord]:
        result = await self._session.execute(select(User).order_by(User.created_at))
        return [_to_record(user) for user in result.scalars().all()]

    async def save(self, record: UserRecord) -> UserRecord:
        user = await self._session.get(User, record.id)
        if user is None:
            user = User(id=record.id)
            self._session.add(user)
        user.username = record.username
        user.display_name = record.display_name
        user.password_hash = record.password_hash
        user.role = record.role
        user.is_active = record.is_active
        if record.last_login_at is not None:
            user.last_login_at = record.last_login_at
        await self._session.flush()
        await self._session.refresh(user)
        return _to_record(user)
