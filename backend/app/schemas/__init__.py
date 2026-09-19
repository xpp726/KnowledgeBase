"""兼容导出与按业务拆分的 HTTP schema 包。

现有模块仍从 ``app.schemas`` 导入，本文件暂时保留原有公开名称。新代码应从
``app.schemas.auth``、``app.schemas.users`` 等业务模块导入，后续再继续拆分本文件。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    index: int = Field(description="引用编号，从 1 开始，与正文中的 [n] 对应")
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int = 0
    score: float = 0.0
    text: str = ""


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
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    refs: list[SourceItem] = Field(default_factory=list)
    created_at: datetime


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="知识库名称")
    description: str = Field(default="", max_length=200)


class KnowledgeBaseOut(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    doc_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentOut(BaseModel):
    doc_id: str
    kb_id: str
    folder_id: str | None = None
    folder_path: str = ""
    file_name: str
    file_ext: str = ""
    file_size: int = 0
    page_count: int = 0
    chunk_count: int = 0
    table_chunks: int = 0
    status: str
    error: str = ""
    created_at: datetime
    updated_at: datetime


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class DocumentSummaryOut(BaseModel):
    total: int
    pending: int
    ingesting: int
    embedding: int
    done: int
    failed: int
    in_progress: int


class DocumentUploadResult(BaseModel):
    doc_id: str
    file_name: str
    folder_id: str | None = None
    status: str
    duplicated: bool = False
    error: str = ""


class ReprocessOut(BaseModel):
    doc_id: str
    status: str


class MoveDocumentsIn(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, description="待移动的文档 id 列表")
    target_folder_id: str = Field(..., min_length=1, description="目标文件夹 id")


class MoveDocumentResult(BaseModel):
    doc_id: str
    status: str
    error: str = ""


class FolderOut(BaseModel):
    folder_id: str
    kb_id: str
    parent_id: str | None = None
    name: str
    depth: int
    is_system: bool = False
    created_at: datetime
    updated_at: datetime


class FolderTreeNode(FolderOut):
    children: list["FolderTreeNode"] = []
    doc_count: int = 0


class FolderTree(BaseModel):
    items: list[FolderTreeNode] = []


class FolderCreate(BaseModel):
    kb_id: str = "default"
    parent_id: str | None = None
    name: str = Field(..., min_length=1, max_length=64, description="folder 名")


class FolderUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class FolderMove(BaseModel):
    parent_id: str | None = None


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


__all__ = [name for name in globals() if not name.startswith("_")]
