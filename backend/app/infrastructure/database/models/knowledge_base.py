"""知识库 ORM 模型。"""

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    kb_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="")
    description: Mapped[str] = mapped_column(Text, default="")
