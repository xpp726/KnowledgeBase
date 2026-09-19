"""知识库数据访问接口。"""

from __future__ import annotations

from typing import Protocol

from app.domain.knowledge_bases.entities import KnowledgeBaseRecord


class KnowledgeBaseRepository(Protocol):
    async def ensure(
        self, kb_id: str, *, name: str | None = None
    ) -> KnowledgeBaseRecord: ...

    async def create(
        self, kb_id: str, *, name: str, description: str = ""
    ) -> KnowledgeBaseRecord: ...

    async def list_all(self) -> list[KnowledgeBaseRecord]: ...

    async def count_documents(self) -> dict[str, int]: ...
