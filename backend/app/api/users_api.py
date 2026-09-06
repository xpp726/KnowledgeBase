"""用户管理接口（admin 专属）。

- GET  /users          用户列表
- POST /users          创建用户
- PUT  /users/{id}     修改用户（角色 / 启用禁用 / 显示名 / 重置密码）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import AsyncSessionLocal
from app.services import auth as auth_svc
from app.services.auth import User, require_admin

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    display_name: str | None = None
    reset_password: str | None = None  # 非空则重置密码


@router.get("")
async def list_users(_: Annotated[User, Depends(require_admin)]) -> dict:
    async with AsyncSessionLocal() as session:
        users = await auth_svc.list_users(session)
    return {"users": [auth_svc.user_to_dict(u) for u in users]}


@router.post("")
async def create_user(
    payload: CreateUserRequest,
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")
    if not payload.username.strip():
        raise HTTPException(status_code=400, detail="用户名不能为空")
    async with AsyncSessionLocal() as session:
        try:
            user = await auth_svc.create_user(
                session,
                username=payload.username.strip(),
                password=payload.password,
                display_name=payload.display_name.strip() or payload.username.strip(),
                role=payload.role,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {"user": auth_svc.user_to_dict(user)}


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    current_admin: Annotated[User, Depends(require_admin)],
) -> dict:
    async with AsyncSessionLocal() as session:
        # 不允许禁用/修改自己
        target = await auth_svc.get_user_by_id(session, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        if target.id == current_admin.id and payload.is_active is False:
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        if target.id == current_admin.id and payload.role is not None and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能降低自己的管理员角色")
        try:
            user = await auth_svc.update_user(
                session,
                user_id,
                role=payload.role,
                is_active=payload.is_active,
                display_name=payload.display_name,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if payload.reset_password:
            if len(payload.reset_password) < 6:
                raise HTTPException(status_code=400, detail="重置密码长度不能少于 6 位")
            await auth_svc.reset_password(session, user_id, payload.reset_password)
            await session.refresh(user)
    return {"user": auth_svc.user_to_dict(user)}
