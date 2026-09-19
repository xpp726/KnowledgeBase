"""文档元数据 ORM 模型。"""

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("folders.folder_id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(default="")
    file_path: Mapped[str] = mapped_column(default="")
    file_ext: Mapped[str] = mapped_column(default="")
    file_size: Mapped[int] = mapped_column(default=0)
    page_count: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    table_chunks: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_documents_folder_filename", "folder_id", "file_name"),)
