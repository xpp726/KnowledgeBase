"""知识库管理接口：列表 / 新建。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import KnowledgeBaseCreate, KnowledgeBaseOut
from app.services import document_service as doc_svc
from app.services.auth import User, get_current_user, require_editor

router = APIRouter(prefix="/kbs", tags=["knowledge-base"])


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(_: Annotated[User, Depends(get_current_user)]):
    return await doc_svc.list_knowledge_bases()


@router.post("", response_model=KnowledgeBaseOut)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    _: Annotated[User, Depends(require_editor)],
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="知识库名称不能为空")
    return await doc_svc.create_knowledge_base(name, body.description.strip())
