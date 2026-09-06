"""认证与权限服务。

- 密码哈希：passlib bcrypt
- JWT：python-jose HS256，payload = {sub: user_id, username, role, exp}
- FastAPI 依赖：get_current_user / require_admin / require_editor
- 用户 CRUD + 初始化默认 admin
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.models.user import User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ROLES = ("admin", "editor", "viewer")


# ---------- 密码 ----------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


# ---------- 用户 CRUD ----------
async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    display_name: str,
    role: str = "viewer",
) -> User:
    if role not in ROLES:
        raise ValueError(f"无效角色: {role}")
    existing = await get_user_by_username(session, username)
    if existing:
        raise ValueError(f"用户名已存在: {username}")
    user = User(
        id=f"u_{int(time.time()*1000)}",
        username=username,
        display_name=display_name or username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(session, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = time.time()
    await session.commit()
    return user


async def update_user(
    session: AsyncSession,
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
) -> User | None:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"无效角色: {role}")
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if display_name is not None:
        user.display_name = display_name
    await session.commit()
    await session.refresh(user)
    return user


async def reset_password(session: AsyncSession, user_id: str, new_password: str) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    user.password_hash = hash_password(new_password)
    await session.commit()
    return True


async def change_password(session: AsyncSession, user_id: str, old_password: str, new_password: str) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user or not verify_password(old_password, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    await session.commit()
    return True


# ---------- 初始化默认 admin ----------
async def ensure_default_admin() -> None:
    """启动时确保至少有一个 admin；无 admin 时创建默认 admin。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.role == "admin", User.is_active == True))
        if result.scalar_one_or_none() is not None:
            return
        admin = User(
            id="u_admin",
            username=settings.default_admin_username,
            display_name=settings.default_admin_display_name,
            password_hash=hash_password(settings.default_admin_password),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()


# ---------- FastAPI 依赖 ----------
async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token")
    user = await get_user_by_id(session, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


async def require_editor(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要编辑者权限")
    return user


# ---------- 序列化 ----------
def user_to_dict(user: User, include_sensitive: bool = False) -> dict:
    d = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "last_login_at": user.last_login_at,
    }
    if include_sensitive:
        d["password_hash"] = user.password_hash
    return d
