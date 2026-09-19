"""API 层依赖装配。

路由只依赖 Application Service，不自行创建数据库 session 或 Repository 实现。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.application.stats.service import StatsApplicationService
from app.application.folders.service import FolderApplicationService
from app.application.users.service import UserApplicationService
from app.bootstrap.container import create_uow
from app.core.security import decode_access_token
from app.domain.users.entities import UserRecord

User = UserRecord
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_user_service() -> AsyncIterator[UserApplicationService]:
    async with create_uow() as uow:
        yield UserApplicationService(uow)


async def get_stats_service() -> AsyncIterator[StatsApplicationService]:
    async with create_uow() as uow:
        yield StatsApplicationService(uow.stats)


def get_folder_service() -> FolderApplicationService:
    """提供无状态 folder 查询服务，每次查询独立获取短事务。"""
    return FolderApplicationService(create_uow)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    service: Annotated[UserApplicationService, Depends(get_user_service)],
) -> UserRecord:
    """通过新 User Repository 读取当前用户，API 不再直接创建 session。"""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token")
    user = await service.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
        )
    return user


async def require_admin(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserRecord:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


async def require_editor(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserRecord:
    if user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要编辑者权限")
    return user
