"""文档领域记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class DocumentRecord:
    """Repository 返回给 Application 的文档快照，不暴露 ORM 生命周期。"""

    doc_id: str
    kb_id: str
    folder_id: str | None
    file_name: str
    file_path: str
    file_ext: str
    file_size: int
    page_count: int
    chunk_count: int
    table_chunks: int
    status: str
    error: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

