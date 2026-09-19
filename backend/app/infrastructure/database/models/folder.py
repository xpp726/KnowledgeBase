"""文件夹 ORM 模型。"""

from sqlalchemy import Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, TimestampMixin


class Folder(Base, TimestampMixin):
    __tablename__ = "folders"

    folder_id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(default="default", index=True)
    parent_id: Mapped[str | None] = mapped_column(default=None, index=True)
    name: Mapped[str] = mapped_column(default="")
    depth: Mapped[int] = mapped_column(default=1)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("uq_folders_kb_parent_name", "kb_id", "parent_id", "name", unique=True),
    )
