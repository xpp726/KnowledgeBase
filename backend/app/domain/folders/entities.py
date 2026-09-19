"""文件夹查询记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FolderRecord:
    folder_id: str
    kb_id: str
    parent_id: str | None
    name: str
    depth: int = 1
    is_system: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
