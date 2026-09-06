"""知识库管理接口：列表 / 新建。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import KnowledgeBaseCreate, KnowledgeBaseOut
from app.services import document_service as doc_svc

router = APIRouter(prefix="/kbs", tags=["knowledge-base"])


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases():
    return await doc_svc.list_knowledge_bases()


@router.post("", response_model=KnowledgeBaseOut)
async def create_knowledge_base(body: KnowledgeBaseCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="知识库名称不能为空")
    return await doc_svc.create_knowledge_base(name, body.description.strip())
