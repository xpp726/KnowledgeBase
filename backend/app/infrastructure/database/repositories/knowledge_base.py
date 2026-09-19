"""知识库 Repository 的 SQLAlchemy 查询实现。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge_bases.entities import KnowledgeBaseRecord
from app.domain.knowledge_bases.repositories import KnowledgeBaseRepository
from app.infrastructure.database.models.document import Document
from app.infrastructure.database.models.knowledge_base import KnowledgeBase


def _to_record(kb: KnowledgeBase) -> KnowledgeBaseRecord:
    return KnowledgeBaseRecord(
        kb_id=kb.kb_id,
        name=kb.name,
        description=kb.description,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


class SqlAlchemyKnowledgeBaseRepository(KnowledgeBaseRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def ensure(self, kb_id: str, *, name: str | None = None):
        kb = await self._session.get(KnowledgeBase, kb_id)
        if kb is None:
            kb = KnowledgeBase(kb_id=kb_id, name=name or kb_id, description="")
            self._session.add(kb)
            await self._session.flush()
        return _to_record(kb)

    async def create(self, kb_id: str, *, name: str, description: str = ""):
        kb = await self._session.get(KnowledgeBase, kb_id)
        if kb is None:
            kb = KnowledgeBase(kb_id=kb_id, name=name, description=description)
            self._session.add(kb)
            await self._session.flush()
        return _to_record(kb)

    async def list_all(self) -> list:
        result = await self._session.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.asc())
        )
        return [_to_record(kb) for kb in result.scalars().all()]

    async def count_documents(self) -> dict[str, int]:
        rows = await self._session.execute(
            select(Document.kb_id, func.count(Document.doc_id)).group_by(Document.kb_id)
        )
        return {kb_id: int(count) for kb_id, count in rows.all()}
