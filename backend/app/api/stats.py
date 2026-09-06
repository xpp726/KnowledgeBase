"""数据统计接口：问答统计聚合（单接口一次返回全部）。

数据源 = query_logs（问答查询记录，含 kb/general 口径、耗时、命中、引用）。
- days：时间范围（近 N 天，None 全量）；mode：all / kb / general。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.models import queries as q
from app.schemas import StatsSummaryOut
from app.db import get_async_session
from app.services.auth import User, get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=StatsSummaryOut)
async def stats_summary(
    _: Annotated[User, Depends(get_current_user)],
    days: int | None = Query(None, ge=1, le=3650, description="近 N 天；不传=全量"),
    mode: str = Query("kb", description="口径：all / kb（知识库问答）/ general（通用问答）"),
):
    if mode not in ("all", "kb", "general"):
        mode = "kb"
    async with get_async_session() as session:
        return await q.stats_summary(session, days=days, mode=mode)
