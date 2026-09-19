"""会话、消息和问答日志 Repository 的 SQLAlchemy 查询实现。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations.entities import ConversationRecord, MessageRecord
from app.domain.conversations.repositories import ConversationRepository
from app.infrastructure.database.models.conversation import Conversation, Message
from app.infrastructure.database.models.log import QueryLog


def _to_conversation(conversation: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=conversation.id,
        kb_id=conversation.kb_id,
        mode=conversation.mode,
        title=conversation.title,
        user_id=conversation.user_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _to_message(message: Message) -> MessageRecord:
    return MessageRecord(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        refs_json=message.refs_json,
        created_at=message.created_at,
    )


class SqlAlchemyConversationRepository(ConversationRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _get_model(self, conversation_id: str) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def get(self, conversation_id: str):
        conversation = await self._get_model(conversation_id)
        return _to_conversation(conversation) if conversation else None

    async def get_for_user(self, conversation_id: str, user_id: str):
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conversation = result.scalar_one_or_none()
        return _to_conversation(conversation) if conversation else None

    async def create(self, **fields: Any):
        now = datetime.now()
        conversation = Conversation(
            id=fields["conv_id"],
            kb_id=fields.get("kb_id", "default"),
            mode=fields.get("mode", "kb"),
            title=fields.get("title", ""),
            user_id=fields.get("user_id", ""),
            created_at=now,
            updated_at=now,
        )
        self._session.add(conversation)
        await self._session.flush()
        return _to_conversation(conversation)

    async def touch(self, conversation_id: str, title: str | None = None) -> None:
        conversation = await self._get_model(conversation_id)
        if conversation is None:
            return
        conversation.updated_at = datetime.now()
        if title and not conversation.title:
            conversation.title = title[:40]
        await self._session.flush()

    async def list_conversations(self, **filters: Any) -> list[Any]:
        statement = select(Conversation)
        for field in ("kb_id", "mode"):
            value = filters.get(field)
            if value is not None and value != "":
                statement = statement.where(getattr(Conversation, field) == value)
        user_id = filters.get("user_id")
        if user_id is not None:
            statement = statement.where(Conversation.user_id == user_id)
        result = await self._session.execute(
            statement.order_by(Conversation.updated_at.desc())
        )
        return [_to_conversation(conversation) for conversation in result.scalars().all()]

    async def list_messages(self, conversation_id: str, limit: int | None = None) -> list[Any]:
        role_order = case((Message.role == "user", 0), else_=1)
        statement = select(Message).where(Message.conversation_id == conversation_id)
        if limit:
            statement = statement.order_by(
                Message.created_at.desc(), role_order.desc(), Message.id.desc()
            ).limit(limit)
            rows = list((await self._session.execute(statement)).scalars().all())
            rows.reverse()
            return [_to_message(message) for message in rows]
        result = await self._session.execute(
            statement.order_by(Message.created_at.asc(), role_order.asc(), Message.id.asc())
        )
        return [_to_message(message) for message in result.scalars().all()]

    async def add_message(self, **fields: Any):
        message = Message(
            id=fields["message_id"],
            conversation_id=fields["conversation_id"],
            role=fields["role"],
            content=fields["content"],
            refs_json=fields.get("refs_json", "[]"),
            created_at=fields.get("created_at", datetime.now()),
        )
        self._session.add(message)
        await self._session.flush()
        return _to_message(message)

    async def add_query_log(self, **fields: Any):
        log = QueryLog(
            id=fields["log_id"],
            conversation_id=fields.get("conversation_id", ""),
            kb_id=fields.get("kb_id", "default"),
            mode=fields.get("mode", "kb"),
            user_id=fields.get("user_id", ""),
            question=fields.get("question", ""),
            answer=fields.get("answer", ""),
            hit_count=fields.get("hit_count", 0),
            refs_json=fields.get("refs_json", "[]"),
            retrieval_ms=fields.get("retrieval_ms", 0.0),
            llm_ms=fields.get("llm_ms", 0.0),
            total_ms=fields.get("total_ms", 0.0),
            created_at=fields.get("created_at", datetime.now()),
        )
        self._session.add(log)
        await self._session.flush()
        return log

    async def delete_rows(self, conversation_id: str) -> None:
        await self._session.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        await self._session.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )
        await self._session.flush()

    async def rename(self, conversation_id: str, title: str):
        conversation = await self._get_model(conversation_id)
        if conversation is None:
            return None
        conversation.title = title[:40]
        conversation.updated_at = datetime.now()
        await self._session.flush()
        return _to_conversation(conversation)
