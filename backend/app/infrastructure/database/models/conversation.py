"""会话与消息 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, LongText, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    mode: Mapped[str] = mapped_column(index=True, default="kb")
    title: Mapped[str] = mapped_column(default="")
    user_id: Mapped[str] = mapped_column(index=True, default="")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(default="")
    content: Mapped[str] = mapped_column(LongText, default="")
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
