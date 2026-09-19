"""会话、消息和问答日志的数据访问接口。"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.conversations.entities import ConversationRecord, MessageRecord


class ConversationRepository(Protocol):
    async def get(self, conversation_id: str) -> ConversationRecord | None: ...

    async def create(self, **fields: Any) -> ConversationRecord: ...

    async def touch(self, conversation_id: str, title: str | None = None) -> None: ...

    async def list_conversations(self, **filters: Any) -> list[ConversationRecord]: ...

    async def list_messages(
        self, conversation_id: str, limit: int | None = None
    ) -> list[MessageRecord]: ...

    async def add_message(self, **fields: Any) -> MessageRecord: ...

    async def add_query_log(self, **fields: Any) -> Any: ...

    async def delete_rows(self, conversation_id: str) -> None: ...

    async def rename(
        self, conversation_id: str, title: str
    ) -> ConversationRecord | None: ...
