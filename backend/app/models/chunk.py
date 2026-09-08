"""分块原文模型。向量在 Milvus，原文在 SQLite/MySQL，检索命中后按 chunk_id 回填。

与旧 db.chunks 表兼容，新增 kb_id 与 Milvus 行对齐。
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, LongText


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(index=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    chunk_index: Mapped[int] = mapped_column(default=0)
    page: Mapped[int] = mapped_column(default=0)
    heading_path: Mapped[str] = mapped_column(default="")
    is_table: Mapped[int] = mapped_column(default=0)
    # 分块原文：长度不可控（整页/整表文本），MySQL 下用 LONGTEXT
    text: Mapped[str] = mapped_column(LongText, default="")
    created_at: Mapped[float] = mapped_column(default=time.time)
