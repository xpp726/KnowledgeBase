"""文件夹 Repository 的 SQLAlchemy 查询实现。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.folders.entities import FolderRecord
from app.domain.folders.repositories import FolderRepository
from app.infrastructure.database.models.document import Document
from app.infrastructure.database.models.folder import Folder
from app.infrastructure.database.models.knowledge_base import KnowledgeBase


def _to_record(folder: Folder) -> FolderRecord:
    return FolderRecord(
        folder_id=folder.folder_id,
        kb_id=folder.kb_id,
        parent_id=folder.parent_id,
        name=folder.name,
        depth=folder.depth,
        is_system=bool(folder.is_system),
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


class SqlAlchemyFolderRepository(FolderRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, folder_id: str) -> FolderRecord | None:
        folder = await self._session.get(Folder, folder_id)
        return _to_record(folder) if folder else None

    async def find_sibling(
        self,
        *,
        kb_id: str,
        parent_id: str | None,
        name: str,
    ) -> FolderRecord | None:
        stmt = select(Folder).where(Folder.kb_id == kb_id, Folder.name == name)
        stmt = stmt.where(
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id
        )
        folder = (await self._session.execute(stmt)).scalars().first()
        return _to_record(folder) if folder else None

    @staticmethod
    def make_id() -> str:
        return f"f_{uuid.uuid4().hex[:12]}"

    async def ensure_knowledge_base(self, kb_id: str, name: str):
        kb = await self._session.get(KnowledgeBase, kb_id)
        if kb is None:
            kb = KnowledgeBase(kb_id=kb_id, name=name or kb_id, description="")
            self._session.add(kb)
            await self._session.flush()
        return kb

    async def ensure_default(self, kb_id: str, name: str = "默认文件夹"):
        stmt = select(Folder).where(
            Folder.kb_id == kb_id,
            Folder.parent_id.is_(None),
            Folder.is_system.is_(True),
        ).limit(1)
        existing = (await self._session.execute(stmt)).scalars().first()
        if existing is not None:
            return _to_record(existing)
        folder = Folder(
            folder_id=self.make_id(),
            kb_id=kb_id,
            parent_id=None,
            name=name,
            depth=1,
            is_system=True,
        )
        self._session.add(folder)
        await self._session.flush()
        return _to_record(folder)

    async def create(
        self,
        *,
        kb_id: str,
        parent_id: str | None,
        name: str,
        depth: int,
        is_system: bool = False,
    ) -> FolderRecord:
        return _to_record(
            await self.create_model(
                kb_id=kb_id,
                parent_id=parent_id,
                name=name,
                depth=depth,
                is_system=is_system,
            )
        )

    async def rename(self, folder_id: str, new_name: str) -> FolderRecord | None:
        folder = await self.get_model(folder_id)
        if folder is None:
            return None
        return _to_record(await self.rename_model(folder, new_name))

    async def move(
        self, folder_id: str, new_parent_id: str | None
    ) -> FolderRecord | None:
        folder = await self.get_model(folder_id)
        if folder is None:
            return None
        return _to_record(await self.move_model(folder, new_parent_id))

    async def list_all(self, kb_id: str) -> list[FolderRecord]:
        return [_to_record(folder) for folder in await self.list_models(kb_id)]

    async def get_default(self, kb_id: str) -> FolderRecord | None:
        statement = select(Folder).where(
            Folder.kb_id == kb_id,
            Folder.parent_id.is_(None),
            Folder.is_system.is_(True),
        ).limit(1)
        folder = (await self._session.execute(statement)).scalars().first()
        return _to_record(folder) if folder else None

    async def list_by_parent(
        self, kb_id: str, parent_id: str | None
    ) -> list[Folder]:
        statement = select(Folder).where(Folder.kb_id == kb_id)
        statement = statement.where(
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def get_model(self, folder_id: str) -> Folder | None:
        return await self._session.get(Folder, folder_id)

    async def find_sibling_model(
        self,
        kb_id: str,
        parent_id: str | None,
        name: str,
    ) -> Folder | None:
        stmt = select(Folder).where(Folder.kb_id == kb_id, Folder.name == name)
        stmt = stmt.where(
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def create_model(
        self,
        *,
        kb_id: str,
        parent_id: str | None,
        name: str,
        depth: int,
        is_system: bool = False,
    ) -> Folder:
        folder = Folder(
            folder_id=self.make_id(),
            kb_id=kb_id,
            parent_id=parent_id,
            name=name,
            depth=depth,
            is_system=is_system,
        )
        self._session.add(folder)
        await self._session.flush()
        return folder

    async def rename_model(self, folder: Folder, new_name: str) -> Folder:
        folder.name = new_name
        folder.updated_at = datetime.now()
        await self._session.flush()
        return folder

    async def move_model(self, folder: Folder, new_parent_id: str | None) -> Folder:
        folder.parent_id = new_parent_id
        folder.updated_at = datetime.now()
        await self._session.flush()
        return folder

    async def list_models(self, kb_id: str) -> list[Folder]:
        result = await self._session.execute(
            select(Folder).where(Folder.kb_id == kb_id).order_by(Folder.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_documents(self, kb_id: str) -> dict[str | None, int]:
        rows = await self._session.execute(
            select(Document.folder_id, func.count(Document.doc_id))
            .where(Document.kb_id == kb_id)
            .group_by(Document.folder_id)
        )
        return {folder_id: int(count) for folder_id, count in rows.all()}

    async def collect_descendants(self, root_ids: list[str]) -> list[str]:
        if not root_ids:
            return []
        all_ids: set[str] = set(root_ids)
        frontier = list(root_ids)
        while frontier:
            result = await self._session.execute(
                select(Folder.folder_id).where(Folder.parent_id.in_(frontier))
            )
            children = [folder_id for folder_id, in result.all()]
            new = [folder_id for folder_id in children if folder_id not in all_ids]
            if not new:
                break
            all_ids.update(new)
            frontier = new
        return sorted(all_ids)

    async def list_document_ids(self, folder_ids: list[str]) -> list[str]:
        if not folder_ids:
            return []
        result = await self._session.execute(
            select(Document.doc_id).where(Document.folder_id.in_(folder_ids))
        )
        return [doc_id for doc_id, in result.all()]

    async def unset_documents(self, doc_ids: list[str]) -> int:
        if not doc_ids:
            return 0
        result = await self._session.execute(
            Document.__table__.update()
            .where(Document.doc_id.in_(doc_ids))
            .values(folder_id=None)
        )
        await self._session.flush()
        return result.rowcount or 0

    async def delete_rows(self, folder_ids: list[str]) -> int:
        if not folder_ids:
            return 0
        result = await self._session.execute(
            delete(Folder).where(Folder.folder_id.in_(folder_ids))
        )
        await self._session.flush()
        return result.rowcount or 0

    async def propagate_depths(self, root_id: str, root_depth: int) -> None:
        """在 Repository 内完成移动后的子树深度重算。"""
        frontier = [(root_id, root_depth)]
        visited: set[str] = {root_id}
        while frontier:
            current_id, current_depth = frontier.pop(0)
            node = await self._session.get(Folder, current_id)
            if node is None:
                continue
            node.depth = current_depth
            await self._session.flush()
            children_stmt = select(Folder.folder_id).where(Folder.parent_id == current_id)
            for child_id, in (await self._session.execute(children_stmt)).all():
                if child_id not in visited:
                    visited.add(child_id)
                    frontier.append((child_id, current_depth + 1))
