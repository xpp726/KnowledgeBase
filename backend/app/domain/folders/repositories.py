"""文件夹数据访问接口。"""

from __future__ import annotations

from typing import Protocol

from app.domain.folders.entities import FolderRecord


class FolderRepository(Protocol):
    async def get_by_id(self, folder_id: str) -> FolderRecord | None: ...

    async def find_sibling(
        self,
        *,
        kb_id: str,
        parent_id: str | None,
        name: str,
    ) -> FolderRecord | None: ...

    async def ensure_knowledge_base(self, kb_id: str, name: str): ...

    async def ensure_default(self, kb_id: str, name: str = "默认文件夹") -> FolderRecord: ...

    async def create(
        self,
        *,
        kb_id: str,
        parent_id: str | None,
        name: str,
        depth: int,
        is_system: bool = False,
    ) -> FolderRecord: ...

    async def rename(self, folder_id: str, new_name: str) -> FolderRecord | None: ...

    async def move(
        self, folder_id: str, new_parent_id: str | None
    ) -> FolderRecord | None: ...

    async def list_all(self, kb_id: str) -> list[FolderRecord]: ...

    async def collect_descendants(self, root_ids: list[str]) -> list[str]: ...

    async def list_document_ids(self, folder_ids: list[str]) -> list[str]: ...

    async def unset_documents(self, doc_ids: list[str]) -> int: ...

    async def delete_rows(self, folder_ids: list[str]) -> int: ...

    async def propagate_depths(self, root_id: str, root_depth: int) -> None: ...
