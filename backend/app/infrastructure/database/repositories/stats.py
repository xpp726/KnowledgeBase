"""统计 Repository 的 SQLAlchemy 实现。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stats.repositories import StatsRepository
from app.infrastructure.database.models.chunk import Chunk
from app.infrastructure.database.models.log import QueryLog
from app.infrastructure.database.models.document import Document


class SqlAlchemyStatsRepository(StatsRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def document_summary(self) -> dict[str, int]:
        documents = (
            await self._session.execute(select(func.count(Document.doc_id)))
        ).scalar() or 0
        chunks = (
            await self._session.execute(select(func.count(Chunk.chunk_id)))
        ).scalar() or 0
        table_chunks = (
            await self._session.execute(
                select(func.count(Chunk.chunk_id)).where(Chunk.is_table == 1)
            )
        ).scalar() or 0
        total_chars = (
            await self._session.execute(
                select(func.coalesce(func.sum(func.length(Chunk.text)), 0))
            )
        ).scalar() or 0
        return {
            "documents": int(documents),
            "chunks": int(chunks),
            "table_chunks": int(table_chunks),
            "total_chars": int(total_chars),
        }

    async def summary(
        self,
        *,
        days: int | None = None,
        mode: str = "all",
    ) -> dict[str, Any]:
        # 统计口径保持与原 queries.stats_summary 一致，迁移只改变调用边界。
        if days:
            start_date = datetime.now().date() - timedelta(days=days - 1)
            since = datetime.combine(start_date, datetime.min.time())
        else:
            start_date = None
            since = datetime.min

        stmt = select(QueryLog).where(QueryLog.created_at >= since)
        if mode in ("kb", "general"):
            stmt = stmt.where(QueryLog.mode == mode)
        rows = (await self._session.execute(stmt)).scalars().all()

        total = len(rows)
        hit_count = sum(1 for row in rows if row.hit_count > 0)
        no_hit = total - hit_count
        hit_rate = hit_count / total * 100 if total else 0.0
        avg_retrieval = sum(row.retrieval_ms for row in rows) / total if total else 0.0
        avg_llm = sum(row.llm_ms for row in rows) / total if total else 0.0
        avg_total = sum(row.total_ms for row in rows) / total if total else 0.0

        by_day: dict[str, list[Any]] = {}
        for row in rows:
            day = row.created_at.date().isoformat()
            bucket = by_day.setdefault(day, [0, 0, 0.0])
            bucket[0] += 1
            if row.hit_count > 0:
                bucket[1] += 1
            bucket[2] += row.total_ms

        def trend_point(day: str, bucket: list[Any]) -> dict[str, Any]:
            return {
                "date": day,
                "count": bucket[0],
                "hit_rate": round(bucket[1] / bucket[0] * 100, 1) if bucket[0] else 0.0,
                "avg_total_ms": round(bucket[2] / bucket[0], 1) if bucket[0] else 0.0,
            }

        trend: list[dict[str, Any]] = []
        if days and start_date is not None:
            cursor = start_date
            end = datetime.now().date()
            while cursor <= end:
                day = cursor.isoformat()
                trend.append(trend_point(day, by_day.get(day, [0, 0, 0.0])))
                cursor += timedelta(days=1)
        else:
            for day in sorted(by_day):
                trend.append(trend_point(day, by_day[day]))

        question_counts: dict[str, int] = {}
        for row in rows:
            question = row.question.strip() or "(空问题)"
            question_counts[question] = question_counts.get(question, 0) + 1
        top_questions = [
            {"question": key, "count": value}
            for key, value in sorted(question_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ]

        doc_counts: dict[str, int] = {}
        for row in rows:
            if not row.refs_json:
                continue
            try:
                refs = json.loads(row.refs_json)
            except (ValueError, TypeError):
                continue
            seen: set[str] = set()
            for ref in refs:
                name = (ref or {}).get("doc_name", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                doc_counts[name] = doc_counts.get(name, 0) + 1
        top_docs = [
            {"doc_name": key, "count": value}
            for key, value in sorted(doc_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ]

        kb_counts: dict[str, int] = {}
        for row in rows:
            kb_id = row.kb_id or "default"
            kb_counts[kb_id] = kb_counts.get(kb_id, 0) + 1
        kb_dist = [
            {"kb_id": key, "count": value}
            for key, value in sorted(kb_counts.items(), key=lambda item: (-item[1], item[0]))
        ]

        return {
            "cards": {
                "total": total,
                "hit_count": hit_count,
                "hit_rate": round(hit_rate, 1),
                "avg_retrieval_ms": round(avg_retrieval, 1),
                "avg_llm_ms": round(avg_llm, 1),
                "avg_total_ms": round(avg_total, 1),
                "no_hit_count": no_hit,
            },
            "trend": trend,
            "top_questions": top_questions,
            "top_docs": top_docs,
            "kb_dist": kb_dist,
        }
