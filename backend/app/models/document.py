"""文档元数据模型。

与旧 db.documents 表字段兼容，新增 kb_id 多知识库维度。
status 状态机：pending → ingesting → embedding → done；失败 → failed。
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    file_name: Mapped[str] = mapped_column(default="")
    # 对象存储 key（MinIO），旧数据为本地路径
    file_path: Mapped[str] = mapped_column(default="")
    file_ext: Mapped[str] = mapped_column(default="")
    file_size: Mapped[int] = mapped_column(default=0)
    page_count: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    table_chunks: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    error: Mapped[str] = mapped_column(default="")
