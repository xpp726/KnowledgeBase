"""文档持久化能力接口。

当前接口的返回值仍允许使用 ORM 兼容对象，这是从旧查询层迁移时的过渡约束；
后续会将返回值逐步收敛为 DocumentRecord/分页 DTO。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.domain.documents.entities import DocumentRecord


class DocumentRepository(Protocol):
    async def get_by_id(self, doc_id: str) -> DocumentRecord | None: ...

    async def status(self, doc_id: str) -> str | None: ...

    async def upsert(self, *, doc_id: str, **fields: Any) -> DocumentRecord: ...

    async def find_by_folder_name(
        self, kb_id: str, folder_id: str, file_name: str
    ) -> DocumentRecord | None: ...

    async def list_page(self, **filters: Any) -> tuple[list[DocumentRecord], int]: ...

    async def count_by_status(self, *, kb_id: str | None = None) -> dict[str, int]: ...

    async def list_stuck(
        self, statuses: set[str], before_ts: datetime
    ) -> list[DocumentRecord]: ...

    async def move_to_folder(self, doc_id: str, folder_id: str) -> None: ...

    async def replace_chunks(
        self, doc_id: str, kb_id: str, chunks: list[dict[str, Any]]
    ) -> int: ...

    async def delete_rows(self, doc_id: str) -> None: ...

    async def list_orphan_kb_ids(self) -> list[str]: ...

    async def assign_folder_for_orphans(self, kb_id: str, folder_id: str) -> int: ...
