"""ORM 基类与通用列 mixin。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# MySQL 要求 VARCHAR 必须显式指定长度，否则建表直接报
# "VARCHAR requires a length on dialect mysql"（MySQL 要求 VARCHAR 显式长度）。
# 这里给 Mapped[str] 统一设默认长度，避免 7 个模型逐个手写 String(n)；
# 内容可能超长的字段请在各自模型里用 Text / LongText 显式覆盖。
DEFAULT_STR_LEN = 255

# 大文本：MySQL 下用 LONGTEXT（上限 4GB），其他方言回落为普通 TEXT。
# 用于 chunk 原文、LLM 回答等长度不可控的内容。
LongText = Text().with_variant(LONGTEXT, "mysql")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。Alembic 通过 Base.metadata 自动发现表。"""

    # 关键：Mapped[str] 默认映射到带长度的 VARCHAR，保证 MySQL 可建表
    type_annotation_map = {str: String(DEFAULT_STR_LEN)}


class TimestampMixin:
    """创建/更新时间戳 mixin。DATETIME 列（本地时间 naive），与 ASR 项目一致。

    历史：早期用 REAL 列存 time.time() 浮点秒（MySQL FLOAT 单精度在 17 亿级会丢精度，
    导致 user/assistant 时间戳相同）；2026-09-13 统一迁移为 DATETIME，
    写入用 datetime.now()（Python 本地时间），前端直接 Date.parse 展示。
    """

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
