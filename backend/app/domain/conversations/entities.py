"""会话领域记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ConversationRecord:
    id: str
    kb_id: str
    mode: str
    title: str
    user_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: str
    content: str
    refs_json: str
    created_at: datetime | None = None

