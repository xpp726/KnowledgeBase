"""认证接口：登录 / 当前用户 / 修改密码。

- POST /auth/login          登录，返回 JWT token + 用户信息
- GET  /auth/me             获取当前登录用户信息
- POST /auth/change-password 修改当前用户密码
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import AsyncSessionLocal
from app.services import auth as auth_svc
from app.services.auth import User, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(payload: LoginRequest) -> dict:
    async with AsyncSessionLocal() as session:
        user = await auth_svc.authenticate(session, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = auth_svc.create_access_token(user)
    return {"token": token, "user": auth_svc.user_to_dict(user)}


@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> dict:
    return auth_svc.user_to_dict(current_user)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
    async with AsyncSessionLocal() as session:
        ok = await auth_svc.change_password(
            session, current_user.id, payload.old_password, payload.new_password
        )
    if not ok:
        raise HTTPException(status_code=400, detail="原密码错误")
    return {"ok": True}
