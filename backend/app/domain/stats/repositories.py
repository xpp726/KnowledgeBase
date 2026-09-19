"""统计读模型的数据访问接口。"""

from __future__ import annotations

from typing import Any, Protocol


class StatsRepository(Protocol):
    async def summary(
        self,
        *,
        days: int | None = None,
        mode: str = "all",
    ) -> dict[str, Any]: ...
