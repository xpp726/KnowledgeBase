"""会话管理接口：列表 / 新建 / 消息历史 / 删除。"""

from __future__ import annotations

from fastapi import APIRouter
from app.schemas import ConversationCreate, ConversationOut, MessageOut, OkResponse
from app.services import conversation_service as conv_svc

router = APIRouter(prefix="/conversations", tags=["conversation"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(kb_id: str | None = None):
    return await conv_svc.list_conversations(kb_id)


@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreate):
    conv_id, _ = await conv_svc.get_or_create_conversation(
        None, kb_id=body.kb_id, title=body.title
    )
    rows = await conv_svc.list_conversations(body.kb_id)
    for row in rows:
        if row["id"] == conv_id:
            return row
    return {"id": conv_id, "kb_id": body.kb_id, "title": body.title,
            "created_at": 0.0, "updated_at": 0.0}


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str):
    return await conv_svc.conversation_messages(conversation_id)


@router.delete("/{conversation_id}", response_model=OkResponse)
async def delete_conversation(conversation_id: str):
    await conv_svc.remove_conversation(conversation_id)
    return OkResponse(detail="deleted")
