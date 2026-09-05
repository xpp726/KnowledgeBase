"""ORM 基类与通用列 mixin。"""

from __future__ import annotations

import time

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。Alembic 通过 Base.metadata 自动发现表。"""


class TimestampMixin:
    """创建/更新时间戳 mixin。沿用旧设计：REAL 列存浮点秒数。"""

    created_at: Mapped[float] = mapped_column(default=time.time)
    updated_at: Mapped[float] = mapped_column(default=time.time, onupdate=time.time)
