"""ORM 基类与通用列 mixin。"""

from __future__ import annotations

import time

from sqlalchemy import Double, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# MySQL 要求 VARCHAR 必须显式指定长度，否则建表直接报
# "VARCHAR requires a length on dialect mysql"（SQLite 无此限制，所以此前没暴露）。
# 这里给 Mapped[str] 统一设默认长度，避免 7 个模型逐个手写 String(n)；
# 内容可能超长的字段请在各自模型里用 Text / LongText 显式覆盖。
DEFAULT_STR_LEN = 255

# 大文本：MySQL 下用 LONGTEXT（上限 4GB），其他方言回落为普通 TEXT。
# 用于 chunk 原文、LLM 回答等长度不可控的内容。
LongText = Text().with_variant(LONGTEXT, "mysql")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。Alembic 通过 Base.metadata 自动发现表。"""

    # 关键：Mapped[str] 默认映射到带长度的 VARCHAR，保证 MySQL 可建表
    type_annotation_map = {str: String(DEFAULT_STR_LEN), float: Double}


class TimestampMixin:
    """创建/更新时间戳 mixin。REAL/DOUBLE 列存浮点秒数。

    注：Mapped[float] 默认被 SQLAlchemy 映射为 MySQL FLOAT（单精度，约 7 位有效数字）。
    在 17 亿级时间戳下 FLOAT 分辨率仅 ~±128s，user/assistant 写入时间差会被舍入成同值，
    导致消息顺序不稳。故在 Base.type_annotation_map 中注册 float -> Double（双精度，微秒级）。
    """

    created_at: Mapped[float] = mapped_column(default=time.time)
    updated_at: Mapped[float] = mapped_column(default=time.time, onupdate=time.time)
