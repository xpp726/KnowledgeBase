"""Pydantic 请求/响应模型（HTTP 层契约）。

只描述 api 边界的数据形状，不含业务逻辑；services 层不依赖这里的模型。
"""

from __future__ import annotations

from typing import Literal

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

# 问答模式：kb=知识库问答（检索+引用）/ general=通用问答（直接 LLM）
ConversationMode = Literal["kb", "general"]


class ConversationCreate(BaseModel):
    kb_id: str = "default"
    title: str = ""
    mode: ConversationMode = "kb"


class ConversationRename(BaseModel):
    title: str = Field(..., min_length=1, description="新的会话标题")


class ConversationOut(BaseModel):
    id: str
    kb_id: str
    mode: str = "kb"
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


# ==================== 知识库 ====================

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="知识库名称")
    description: str = Field(default="", max_length=200)


class KnowledgeBaseOut(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    doc_count: int = 0
    created_at: float
    updated_at: float


# ==================== 文档 ====================

class DocumentOut(BaseModel):
    doc_id: str
    kb_id: str
    file_name: str
    file_ext: str = ""
    file_size: int = 0
    page_count: int = 0
    chunk_count: int = 0
    table_chunks: int = 0
    status: str
    error: str = ""
    created_at: float
    updated_at: float


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class DocumentUploadResult(BaseModel):
    doc_id: str
    file_name: str
    status: str
    duplicated: bool = False
    error: str = ""


class ReprocessOut(BaseModel):
    doc_id: str
    status: str


# ==================== 运行日志 ====================

class LogEntryOut(BaseModel):
    line_no: int
    ts: str = ""
    level: str = "OTHER"
    source: str = ""
    message: str = ""


class LogEntriesOut(BaseModel):
    items: list[LogEntryOut]
    next_end_line: int | None = None


class LogFileOut(BaseModel):
    name: str
    size_bytes: int = 0
    mtime: float = 0.0
    is_rotated: bool = False


# ==================== 数据统计 ====================

class StatsCardsOut(BaseModel):
    total: int = 0
    hit_count: int = 0
    hit_rate: float = 0.0
    avg_retrieval_ms: float = 0.0
    avg_llm_ms: float = 0.0
    avg_total_ms: float = 0.0
    no_hit_count: int = 0


class StatsTrendPointOut(BaseModel):
    date: str
    count: int = 0
    hit_rate: float = 0.0
    avg_total_ms: float = 0.0


class StatsTopQuestionOut(BaseModel):
    question: str
    count: int = 0


class StatsTopDocOut(BaseModel):
    doc_name: str
    count: int = 0


class StatsKbDistOut(BaseModel):
    kb_id: str
    count: int = 0


class StatsSummaryOut(BaseModel):
    cards: StatsCardsOut
    trend: list[StatsTrendPointOut] = []
    top_questions: list[StatsTopQuestionOut] = []
    top_docs: list[StatsTopDocOut] = []
    kb_dist: list[StatsKbDistOut] = []
