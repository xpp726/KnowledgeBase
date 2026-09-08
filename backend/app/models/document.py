"""文档元数据模型。

与旧 db.documents 表字段兼容，新增 kb_id 多知识库维度与 folder_id 树状组织维度。
status 状态机：pending → ingesting → embedding → done；失败 → failed。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    # 树状组织：folder_id 指向 folders.folder_id；nullable 用于迁移期/兼容旧数据
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("folders.folder_id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(default="")
    # 对象存储 key（MinIO），旧数据为本地路径
    file_path: Mapped[str] = mapped_column(default="")
    file_ext: Mapped[str] = mapped_column(default="")
    file_size: Mapped[int] = mapped_column(default=0)
    page_count: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    table_chunks: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    # 失败原因：可能是完整异常堆栈，长度不可控
    error: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        # 文件在同 folder 内 name 唯一——upload 时由 service 层校验，
        # 这里建联合索引便于"已存在的文件"查询
        Index("ix_documents_folder_filename", "folder_id", "file_name"),
    )
