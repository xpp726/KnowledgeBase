"""用户管理接口（admin 专属）。

- GET  /users          用户列表
- POST /users          创建用户
- PUT  /users/{id}     修改用户（角色 / 启用禁用 / 显示名 / 重置密码）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import User, get_user_service, require_admin
from app.application.users.service import UserApplicationService, user_to_dict
from app.schemas.users import CreateUserRequest, UpdateUserRequest


router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(
    _: Annotated[User, Depends(require_admin)],
    service: UserApplicationService = Depends(get_user_service),
) -> dict:
    users = await service.list_users()
    return {"users": [user_to_dict(u) for u in users]}


@router.post("")
async def create_user(
    payload: CreateUserRequest,
    _: Annotated[User, Depends(require_admin)],
    service: UserApplicationService = Depends(get_user_service),
) -> dict:
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")
    if not payload.username.strip():
        raise HTTPException(status_code=400, detail="用户名不能为空")
    try:
        user = await service.create_user(
            username=payload.username.strip(),
            password=payload.password,
            display_name=payload.display_name.strip() or payload.username.strip(),
            role=payload.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"user": user_to_dict(user)}


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    current_admin: Annotated[User, Depends(require_admin)],
    service: UserApplicationService = Depends(get_user_service),
) -> dict:
    try:
        user = await service.update_user(
            user_id,
            actor_id=current_admin.id,
            role=payload.role,
            is_active=payload.is_active,
            display_name=payload.display_name,
            reset_password=payload.reset_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": user_to_dict(user)}
