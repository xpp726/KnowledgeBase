"""ORM 基类与通用列 mixin。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_STR_LEN = 255
LongText = Text().with_variant(LONGTEXT, "mysql")


class Base(DeclarativeBase):
    type_annotation_map = {str: String(DEFAULT_STR_LEN)}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
