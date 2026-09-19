"""用户领域记录。

这是持久化层返回给 Application Service 的轻量记录，不暴露 SQLAlchemy
ORM 对象，避免业务层依赖 session、关系加载和 ORM 生命周期。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class UserRecord:
    id: str
    username: str
    display_name: str
    password_hash: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
