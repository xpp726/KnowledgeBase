"""测试数据库辅助函数：只通过业务 Repository 准备和读取数据。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.database.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.document import SqlAlchemyDocumentRepository
from app.infrastructure.database.repositories.folder import SqlAlchemyFolderRepository
from app.infrastructure.database.repositories.knowledge_base import (
    SqlAlchemyKnowledgeBaseRepository,
)
from app.infrastructure.database.repositories.stats import SqlAlchemyStatsRepository


async def ensure_knowledge_base(session, kb_id: str, name: str | None = None):
    return await SqlAlchemyKnowledgeBaseRepository(session).ensure(kb_id, name=name)


async def create_knowledge_base(
    session, kb_id: str, *, name: str, description: str = ""
):
    return await SqlAlchemyKnowledgeBaseRepository(session).create(
        kb_id, name=name, description=description
    )


async def list_knowledge_bases(session):
    return await SqlAlchemyKnowledgeBaseRepository(session).list_all()


async def count_documents_by_kb(session):
    return await SqlAlchemyKnowledgeBaseRepository(session).count_documents()


async def ensure_default_folder(session, kb_id: str, name: str = "默认文件夹"):
    return await SqlAlchemyFolderRepository(session).ensure_default(kb_id, name=name)


async def get_default_folder(session, kb_id: str):
    return await SqlAlchemyFolderRepository(session).get_default(kb_id)


async def create_folder(
    session,
    *,
    kb_id: str,
    parent_id: str | None,
    name: str,
    depth: int,
    is_system: bool = False,
):
    return await SqlAlchemyFolderRepository(session).create(
        kb_id=kb_id,
        parent_id=parent_id,
        name=name,
        depth=depth,
        is_system=is_system,
    )


async def upsert_document(session, *, doc_id: str, **fields: Any):
    return await SqlAlchemyDocumentRepository(session).upsert(doc_id=doc_id, **fields)


async def get_document(session, doc_id: str):
    return await SqlAlchemyDocumentRepository(session).get_by_id(doc_id)


async def document_status(session, doc_id: str):
    return await SqlAlchemyDocumentRepository(session).status(doc_id)


async def paginate_documents(session, **filters: Any):
    return await SqlAlchemyDocumentRepository(session).list_page(**filters)


async def add_query_log(session, **fields: Any):
    return await SqlAlchemyConversationRepository(session).add_query_log(**fields)


async def stats_summary(session, *, days: int | None = None, mode: str = "all"):
    return await SqlAlchemyStatsRepository(session).summary(days=days, mode=mode)

