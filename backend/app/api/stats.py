"""数据统计接口：问答统计聚合（单接口一次返回全部）。

数据源 = query_logs（问答查询记录，含 kb/general 口径、耗时、命中、引用）。
- days：时间范围（近 N 天，None 全量）；mode：all / kb / general。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import User, get_current_user, get_stats_service
from app.application.stats.service import StatsApplicationService
from app.schemas import StatsSummaryOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=StatsSummaryOut)
async def stats_summary(
    _: Annotated[User, Depends(get_current_user)],
    service: Annotated[StatsApplicationService, Depends(get_stats_service)],
    days: int | None = Query(None, ge=1, le=3650, description="近 N 天；不传=全量"),
    mode: str = Query("kb", description="口径：all / kb（知识库问答）/ general（通用问答）"),
):
    return await service.summary(days=days, mode=mode)
