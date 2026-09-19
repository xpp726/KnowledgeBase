"""查询日志 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base, LongText


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(default="")
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    mode: Mapped[str] = mapped_column(default="kb")
    user_id: Mapped[str] = mapped_column(index=True, default="")
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(LongText, default="")
    hit_count: Mapped[int] = mapped_column(default=0)
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    retrieval_ms: Mapped[float] = mapped_column(default=0.0)
    llm_ms: Mapped[float] = mapped_column(default=0.0)
    total_ms: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
