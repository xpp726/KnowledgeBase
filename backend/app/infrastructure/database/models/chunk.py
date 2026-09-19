"""分块原文 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, LongText


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(index=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    chunk_index: Mapped[int] = mapped_column(default=0)
    page: Mapped[int] = mapped_column(default=0)
    heading_path: Mapped[str] = mapped_column(default="")
    is_table: Mapped[int] = mapped_column(default=0)
    text: Mapped[str] = mapped_column(LongText, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
