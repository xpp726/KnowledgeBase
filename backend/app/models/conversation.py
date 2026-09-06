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
    # 问答模式：kb=知识库问答（检索+引用）/ general=通用问答（直接 LLM）
    mode: Mapped[str] = mapped_column(index=True, default="kb")
    title: Mapped[str] = mapped_column(default="")
    # 所属用户（权限体系后加入；历史数据为空表示迁移前数据）
    user_id: Mapped[str] = mapped_column(index=True, default="")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(default="")
    content: Mapped[str] = mapped_column(default="")
    refs_json: Mapped[str] = mapped_column(default="[]")
    created_at: Mapped[float] = mapped_column(default=0.0)
