"""知识库领域记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class KnowledgeBaseRecord:
    kb_id: str
    name: str
    description: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

