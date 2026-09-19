"""用户 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str] = mapped_column(default="")
    password_hash: Mapped[str] = mapped_column(default="")
    role: Mapped[str] = mapped_column(default="viewer")
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
