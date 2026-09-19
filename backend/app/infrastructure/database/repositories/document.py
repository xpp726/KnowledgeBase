"""文档和分块 Repository 的 SQLAlchemy 查询实现。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents.entities import DocumentRecord
from app.domain.documents.repositories import DocumentRepository
from app.infrastructure.database.models.chunk import Chunk
from app.infrastructure.database.models.document import Document


def _to_record(document: Document) -> DocumentRecord:
    return DocumentRecord(
        doc_id=document.doc_id,
        kb_id=document.kb_id,
        folder_id=document.folder_id,
        file_name=document.file_name,
        file_path=document.file_path,
        file_ext=document.file_ext,
        file_size=document.file_size,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        table_chunks=document.table_chunks,
        status=document.status,
        error=document.error,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


class SqlAlchemyDocumentRepository(DocumentRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, doc_id: str):
        document = await self._session.get(Document, doc_id)
        return _to_record(document) if document else None

    async def status(self, doc_id: str) -> str | None:
        document = await self._session.get(Document, doc_id)
        return document.status if document else None

    async def upsert(self, *, doc_id: str, **fields: Any):
        now = datetime.now()
        document = await self._session.get(Document, doc_id)
        if document is None:
            document = Document(doc_id=doc_id, created_at=now, updated_at=now, **fields)
            self._session.add(document)
        else:
            for key, value in fields.items():
                setattr(document, key, value)
            document.updated_at = now
        await self._session.flush()
        return _to_record(document)

    async def find_by_folder_name(self, kb_id: str, folder_id: str, file_name: str):
        result = await self._session.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.folder_id == folder_id,
                Document.file_name == file_name,
            )
        )
        document = result.scalars().first()
        return _to_record(document) if document else None

    async def list_page(self, **filters: Any) -> tuple[list[DocumentRecord], int]:
        kb_id = filters.get("kb_id")
        status = filters.get("status")
        search = filters.get("search")
        folder_id = filters.get("folder_id")
        page = filters.get("page", 1)
        page_size = filters.get("page_size", 20)
        conditions = []
        if kb_id:
            conditions.append(Document.kb_id == kb_id)
        if folder_id:
            conditions.append(Document.folder_id == folder_id)
        if status:
            conditions.append(Document.status == status)
        if search:
            conditions.append(Document.file_name.ilike(f"%{search}%"))

        statement = select(Document)
        count_statement = select(func.count(Document.doc_id))
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        total = (await self._session.execute(count_statement)).scalar() or 0
        statement = statement.order_by(Document.updated_at.desc())
        if page_size > 0:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(statement)
        return [_to_record(document) for document in result.scalars().all()], int(total)

    async def list_by_status(
        self,
        *,
        kb_id: str | None = None,
        status: str | None = None,
    ) -> list[DocumentRecord]:
        statement = select(Document)
        if kb_id:
            statement = statement.where(Document.kb_id == kb_id)
        if status:
            statement = statement.where(Document.status == status)
        statement = statement.order_by(Document.updated_at.desc())
        result = await self._session.execute(statement)
        return [_to_record(document) for document in result.scalars().all()]

    async def count_by_status(self, *, kb_id: str | None = None) -> dict[str, int]:
        statement = select(Document.status, func.count(Document.doc_id))
        if kb_id:
            statement = statement.where(Document.kb_id == kb_id)
        result = await self._session.execute(statement.group_by(Document.status))
        return {status: int(count) for status, count in result.all()}

    async def list_stuck(self, statuses: set[str], before_ts: datetime) -> list[DocumentRecord]:
        if not statuses:
            return []
        statement = (
            select(Document)
            .where(Document.status.in_(statuses))
            .where(Document.updated_at < before_ts)
            .order_by(Document.updated_at.asc())
        )
        result = await self._session.execute(statement)
        return [_to_record(document) for document in result.scalars().all()]

    async def move_to_folder(self, doc_id: str, folder_id: str) -> None:
        document = await self._session.get(Document, doc_id)
        if document is not None:
            document.folder_id = folder_id
            await self._session.flush()

    async def replace_chunks(
        self,
        doc_id: str,
        kb_id: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        await self._session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
        now = datetime.now()
        self._session.add_all(
            [
                Chunk(
                    chunk_id=chunk["chunk_id"],
                    doc_id=doc_id,
                    kb_id=kb_id,
                    chunk_index=chunk["index"],
                    page=chunk.get("page", 0),
                    heading_path=chunk.get("heading_path", ""),
                    is_table=int(bool(chunk.get("is_table"))),
                    text=chunk["text"],
                    created_at=now,
                )
                for chunk in chunks
            ]
        )
        await self._session.flush()
        return len(chunks)

    async def delete_rows(self, doc_id: str) -> None:
        await self._session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
        await self._session.execute(delete(Document).where(Document.doc_id == doc_id))
        await self._session.flush()

    async def list_orphan_kb_ids(self) -> list[str]:
        result = await self._session.execute(
            select(Document.kb_id)
            .where(Document.folder_id.is_(None))
            .where(Document.kb_id.is_not(None))
            .group_by(Document.kb_id)
        )
        return [kb_id for (kb_id,) in result.all() if kb_id]

    async def assign_folder_for_orphans(self, kb_id: str, folder_id: str) -> int:
        result = await self._session.execute(
            update(Document)
            .where(Document.kb_id == kb_id, Document.folder_id.is_(None))
            .values(folder_id=folder_id)
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[Any]:
        if not chunk_ids:
            return []
        result = await self._session.execute(
            select(Chunk).where(Chunk.chunk_id.in_(chunk_ids))
        )
        by_id = {chunk.chunk_id: chunk for chunk in result.scalars().all()}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    async def list_all(self, *, kb_id: str | None = None, status: str | None = None,
                       folder_id: str | None = None) -> list[Any]:
        statement = select(Document)
        if kb_id:
            statement = statement.where(Document.kb_id == kb_id)
        if folder_id:
            statement = statement.where(Document.folder_id == folder_id)
        if status:
            statement = statement.where(Document.status == status)
        result = await self._session.execute(statement.order_by(Document.updated_at.desc()))
        return [_to_record(document) for document in result.scalars().all()]
