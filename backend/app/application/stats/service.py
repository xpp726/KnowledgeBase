"""统计查询用例。"""

from __future__ import annotations

from typing import Any

from app.domain.stats.repositories import StatsRepository


class StatsApplicationService:
    def __init__(self, repository: StatsRepository):
        self._repository = repository

    async def summary(self, *, days: int | None = None, mode: str = "kb") -> dict[str, Any]:
        if mode not in ("all", "kb", "general"):
            mode = "kb"
        return await self._repository.summary(days=days, mode=mode)
