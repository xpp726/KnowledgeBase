"""用户数据访问接口。"""

from __future__ import annotations

from typing import Protocol

from app.domain.users.entities import UserRecord


class UserRepository(Protocol):
    async def get_by_username(self, username: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: str) -> UserRecord | None: ...

    async def list_all(self) -> list[UserRecord]: ...

    async def save(self, user: UserRecord) -> UserRecord: ...
