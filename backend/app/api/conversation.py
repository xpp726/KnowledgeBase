"""会话管理接口：列表 / 新建 / 改名 / 消息历史 / 删除。

所有接口需登录；会话按 user_id 隔离，用户只能看到/操作自己的会话。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from app.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    MessageOut,
    OkResponse,
)
from app.services import conversation_service as conv_svc
from app.services.auth import User, get_current_user

router = APIRouter(prefix="/conversations", tags=["conversation"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    kb_id: str | None = None,
    mode: str | None = None,
):
    return await conv_svc.list_conversations(kb_id, mode, user_id=current_user.id)


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
):
    conv_id, _ = await conv_svc.get_or_create_conversation(
        None, kb_id=body.kb_id, title=body.title, mode=body.mode, user_id=current_user.id
    )
    rows = await conv_svc.list_conversations(body.kb_id, body.mode, user_id=current_user.id)
    for row in rows:
        if row["id"] == conv_id:
            return row
    return {"id": conv_id, "kb_id": body.kb_id, "mode": body.mode, "title": body.title,
            "created_at": 0.0, "updated_at": 0.0}


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: str,
    body: ConversationRename,
    current_user: Annotated[User, Depends(get_current_user)],
):
    # 校验会话归属
    rows = await conv_svc.list_conversations(user_id=current_user.id)
    if not any(r["id"] == conversation_id for r in rows):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    row = await conv_svc.rename_conversation(conversation_id, body.title)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    rows = await conv_svc.list_conversations(user_id=current_user.id)
    if not any(r["id"] == conversation_id for r in rows):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return await conv_svc.conversation_messages(conversation_id)


@router.delete("/{conversation_id}", response_model=OkResponse)
async def delete_conversation(
    conversation_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    rows = await conv_svc.list_conversations(user_id=current_user.id)
    if not any(r["id"] == conversation_id for r in rows):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    await conv_svc.remove_conversation(conversation_id)
    return OkResponse(detail="deleted")
