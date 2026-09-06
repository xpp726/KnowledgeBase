"""系统设置接口：系统信息 / 参数白名单 / 保存 / 连通性诊断。

- GET  /config/system      系统信息（只读）
- GET  /config/params      可编辑白名单当前值 + 基础设施只读（敏感字段掩码）
- PUT  /config/params      保存参数（校验 → 写回 .env → 触发热重载）
- GET  /config/diagnostics 连通性诊断（复用 health 探测：LLM / Embedding / Milvus）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services import config_service, health

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/system")
async def system_info() -> dict:
    return config_service.get_system_info(get_settings())


@router.get("/params")
async def get_params() -> dict:
    return config_service.get_params_snapshot(get_settings())


@router.put("/params")
async def save_params(payload: dict) -> dict:
    try:
        return config_service.save_params(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/diagnostics")
async def diagnostics() -> dict:
    return await health.full_health()
