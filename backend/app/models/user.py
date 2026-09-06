"""用户模型（认证与权限）。

角色：admin（全部权限）/ editor（文档管理+问答）/ viewer（仅问答+查看）。
is_active 软删除，禁用而非物理删除，保留审计链。
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str] = mapped_column(default="")
    password_hash: Mapped[str] = mapped_column(default="")
    role: Mapped[str] = mapped_column(default="viewer")  # admin / editor / viewer
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[float] = mapped_column(default=0.0)
