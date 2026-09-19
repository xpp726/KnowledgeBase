"""健康检查端点：只做路由与响应，探测逻辑在 infrastructure/health。"""

from __future__ import annotations

from fastapi import APIRouter

from app.infrastructure.health import checks as health_service

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """一次性验证全部依赖服务（LLM / Embedding / Milvus）。"""
    return await health_service.full_health()
