"""认证接口：登录 / 当前用户 / 修改密码。

- POST /auth/login          登录，返回 JWT token + 用户信息
- GET  /auth/me             获取当前登录用户信息
- POST /auth/change-password 修改当前用户密码
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import User, get_current_user, get_user_service
from app.application.users.service import UserApplicationService, user_to_dict
from app.core.security import create_access_token
from app.schemas.auth import ChangePasswordRequest, LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    payload: LoginRequest,
    service: UserApplicationService = Depends(get_user_service),
) -> dict:
    user = await service.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(user)
    return {"token": token, "user": user_to_dict(user)}


@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> dict:
    return user_to_dict(current_user)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: UserApplicationService = Depends(get_user_service),
) -> dict:
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
    ok = await service.change_password(
        current_user.id, payload.old_password, payload.new_password
    )
    if not ok:
        raise HTTPException(status_code=400, detail="原密码错误")
    return {"ok": True}
