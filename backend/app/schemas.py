"""Pydantic 请求/响应模型（HTTP 层契约）。

只描述 api 边界的数据形状，不含业务逻辑；services 层不依赖这里的模型。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ==================== 检索引用 ====================

class SourceItem(BaseModel):
    """一条引用来源，SSE references 事件与会话消息 refs 都用它。"""

    index: int = Field(description="引用编号，从 1 开始，与正文中的 [n] 对应")
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int = 0
    score: float = 0.0
    text: str = ""


# ==================== 会话 ====================

class ConversationCreate(BaseModel):
    kb_id: str = "default"
    title: str = ""


class ConversationOut(BaseModel):
    id: str
    kb_id: str
    title: str
    created_at: float
    updated_at: float


# ==================== 消息 ====================

class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    refs: list[SourceItem] = Field(default_factory=list)
    created_at: float


# ==================== 通用 ====================

class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""
