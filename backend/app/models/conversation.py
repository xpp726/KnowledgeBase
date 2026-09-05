"""会话与消息模型。

会话挂在知识库下（kb_id），消息属于会话。refs_json 存引用的 chunk_id 列表。
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    title: Mapped[str] = mapped_column(default="")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(default="")
    content: Mapped[str] = mapped_column(default="")
    refs_json: Mapped[str] = mapped_column(default="[]")
    created_at: Mapped[float] = mapped_column(default=0.0)
