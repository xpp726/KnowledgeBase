"""会话归属校验测试。"""

from __future__ import annotations

import pytest

from app.application.conversations import service
from app.domain.conversations.entities import ConversationRecord, MessageRecord


class FakeConversationRepository:
    def __init__(self) -> None:
        self.conversations = {
            "c_owner": ConversationRecord(
                id="c_owner",
                kb_id="default",
                mode="kb",
                title="owner",
                user_id="u_owner",
            ),
        }

    async def get(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    async def get_for_user(self, conversation_id: str, user_id: str):
        conversation = self.conversations.get(conversation_id)
        if conversation is not None and conversation.user_id == user_id:
            return conversation
        return None

    async def list_messages(self, conversation_id: str, limit: int | None = None):
        return [
            MessageRecord(
                id="m1",
                conversation_id=conversation_id,
                role="user",
                content="私有内容",
                refs_json="[]",
            )
        ]

    async def touch(self, conversation_id: str, title: str | None = None) -> None:
        return None

    async def create(self, **fields):
        raise AssertionError("越权会话不应创建或复用")


class FakeUnitOfWork:
    def __init__(self, repository: FakeConversationRepository) -> None:
        self.conversations = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_history_rejects_conversation_owned_by_another_user(monkeypatch):
    repository = FakeConversationRepository()
    monkeypatch.setattr(
        service,
        "create_uow",
        lambda: FakeUnitOfWork(repository),
    )

    with pytest.raises(service.ConversationAccessError):
        await service.history_for_prompt("c_owner", user_id="u_other")


@pytest.mark.asyncio
async def test_get_or_create_does_not_reuse_another_users_conversation(monkeypatch):
    repository = FakeConversationRepository()
    monkeypatch.setattr(
        service,
        "create_uow",
        lambda: FakeUnitOfWork(repository),
    )

    with pytest.raises(service.ConversationAccessError):
        await service.get_or_create_conversation(
            "c_owner",
            title="攻击者输入",
            user_id="u_other",
        )
