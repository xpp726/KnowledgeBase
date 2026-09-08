"""查询日志模型（阶段 3 统计报表用）。"""

from __future__ import annotations

import time

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, LongText


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(default="")
    kb_id: Mapped[str] = mapped_column(index=True, default="default")
    mode: Mapped[str] = mapped_column(default="kb")  # kb（知识库问答）/ general（通用问答）
    user_id: Mapped[str] = mapped_column(index=True, default="")  # 所属用户（权限体系后加入）
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(LongText, default="")
    hit_count: Mapped[int] = mapped_column(default=0)
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    retrieval_ms: Mapped[float] = mapped_column(default=0.0)
    llm_ms: Mapped[float] = mapped_column(default=0.0)
    total_ms: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[float] = mapped_column(default=time.time, index=True)
