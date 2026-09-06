"""ORM 查询/写入函数（轻量收拢，不做 repository 抽象）。

约定：
- 所有函数接收 ``AsyncSession``，内部只 ``flush`` 不 ``commit``，
  事务边界由调用方（db.get_async_session 上下文）统一控制，
  便于 ingestion 分阶段落库、service 组合多步操作。
- 这是"可复用、可单测的函数集合"，不是一接口多实现的 repository；
  换库由 SQLAlchemy 方言层覆盖，无需额外抽象。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.log import QueryLog


# ==================== 知识库 ====================

async def ensure_knowledge_base(
    session: AsyncSession, kb_id: str, name: str | None = None
) -> KnowledgeBase:
    """知识库不存在则创建，返回已存在或新建的实例。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        kb = KnowledgeBase(kb_id=kb_id, name=name or kb_id, description="")
        session.add(kb)
        await session.flush()
    return kb


# ==================== 文档 ====================

async def get_document(session: AsyncSession, doc_id: str) -> Document | None:
    return await session.get(Document, doc_id)


async def document_status(session: AsyncSession, doc_id: str) -> str | None:
    doc = await session.get(Document, doc_id)
    return doc.status if doc else None


async def upsert_document(session: AsyncSession, *, doc_id: str, **fields: Any) -> Document:
    """新增或更新文档记录，自动维护 updated_at。"""
    now = time.time()
    doc = await session.get(Document, doc_id)
    if doc is not None:
        for key, value in fields.items():
            setattr(doc, key, value)
        doc.updated_at = now
    else:
        doc = Document(doc_id=doc_id, created_at=now, updated_at=now, **fields)
        session.add(doc)
    await session.flush()
    return doc


async def list_documents(
    session: AsyncSession, kb_id: str | None = None, status: str | None = None
) -> list[Document]:
    stmt = select(Document)
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    if status:
        stmt = stmt.where(Document.status == status)
    stmt = stmt.order_by(Document.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_document_rows(session: AsyncSession, doc_id: str) -> None:
    """删除文档的 DB 记录及其全部 chunk 原文（不含向量/文件，那是补偿流程的事）。"""
    await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    await session.execute(delete(Document).where(Document.doc_id == doc_id))
    await session.flush()


async def list_stuck_documents(
    session: AsyncSession, statuses: set[str], before_ts: float
) -> list[Document]:
    """找处于给定处理态、且 updated_at 早于 before_ts 的文档（启动卡死恢复用）。"""
    if not statuses:
        return []
    stmt = (
        select(Document)
        .where(Document.status.in_(statuses))
        .where(Document.updated_at < before_ts)
        .order_by(Document.updated_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ==================== 分块原文 ====================

async def replace_chunks(
    session: AsyncSession, doc_id: str, kb_id: str, chunks: list[dict[str, Any]]
) -> int:
    """整篇替换分块原文：先清旧再插新，避免重新入库残留脏数据。"""
    await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    now = time.time()
    session.add_all(
        [
            Chunk(
                chunk_id=c["chunk_id"],
                doc_id=doc_id,
                kb_id=kb_id,
                chunk_index=c["index"],
                page=c.get("page", 0),
                heading_path=c.get("heading_path", ""),
                is_table=int(bool(c.get("is_table"))),
                text=c["text"],
                created_at=now,
            )
            for c in chunks
        ]
    )
    await session.flush()
    return len(chunks)


async def get_chunks_by_ids(session: AsyncSession, chunk_ids: list[str]) -> list[Chunk]:
    """按 chunk_id 批量取原文，保持传入顺序。"""
    if not chunk_ids:
        return []
    result = await session.execute(select(Chunk).where(Chunk.chunk_id.in_(chunk_ids)))
    by_id = {c.chunk_id: c for c in result.scalars().all()}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]


# ==================== 统计 ====================

async def stats(session: AsyncSession) -> dict[str, int]:
    docs = (await session.execute(select(func.count(Document.doc_id)))).scalar() or 0
    chunks = (await session.execute(select(func.count(Chunk.chunk_id)))).scalar() or 0
    tables = (
        await session.execute(
            select(func.count(Chunk.chunk_id)).where(Chunk.is_table == 1)
        )
    ).scalar() or 0
    chars = (
        await session.execute(select(func.coalesce(func.sum(func.length(Chunk.text)), 0)))
    ).scalar() or 0
    return {
        "documents": int(docs),
        "chunks": int(chunks),
        "table_chunks": int(tables),
        "total_chars": int(chars),
    }


# ==================== 会话 ====================

async def create_conversation(
    session: AsyncSession,
    conv_id: str,
    kb_id: str = "default",
    title: str = "",
    mode: str = "kb",
) -> Conversation:
    now = time.time()
    conv = Conversation(
        id=conv_id, kb_id=kb_id, mode=mode, title=title, created_at=now, updated_at=now
    )
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, conv_id: str) -> Conversation | None:
    return await session.get(Conversation, conv_id)


async def list_conversations(
    session: AsyncSession, kb_id: str | None = None, mode: str | None = None
) -> list[Conversation]:
    stmt = select(Conversation)
    if kb_id:
        stmt = stmt.where(Conversation.kb_id == kb_id)
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    stmt = stmt.order_by(Conversation.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def touch_conversation(session: AsyncSession, conv_id: str, title: str | None = None) -> None:
    """更新会话的最近活跃时间；title 非空且原标题为空时用它补标题。"""
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return
    conv.updated_at = time.time()
    if title and not conv.title:
        conv.title = title[:40]
    await session.flush()


async def rename_conversation(session: AsyncSession, conv_id: str, title: str) -> Conversation | None:
    """覆盖会话标题并刷新 updated_at；不存在返回 None（供上层映射 404）。"""
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return None
    conv.title = title[:40]
    conv.updated_at = time.time()
    await session.flush()
    return conv


async def delete_conversation_rows(session: AsyncSession, conv_id: str) -> None:
    """删除会话及其全部消息（query_logs 保留作统计，仅断开关联）。"""
    await session.execute(delete(Message).where(Message.conversation_id == conv_id))
    await session.execute(delete(Conversation).where(Conversation.id == conv_id))
    await session.flush()


# ==================== 消息 ====================

async def add_message(
    session: AsyncSession,
    *,
    message_id: str,
    conversation_id: str,
    role: str,
    content: str,
    refs_json: str = "[]",
    created_at: float | None = None,
) -> Message:
    msg = Message(
        id=message_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        refs_json=refs_json,
        created_at=created_at if created_at is not None else time.time(),
    )
    session.add(msg)
    await session.flush()
    return msg


async def list_messages(
    session: AsyncSession, conversation_id: str, limit: int | None = None
) -> list[Message]:
    """取会话消息，按时间正序返回；limit 非空时先取最近 limit 条再转正序（拼历史用）。"""
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if limit:
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows
    stmt = stmt.order_by(Message.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


# ==================== 查询日志 ====================

async def add_query_log(
    session: AsyncSession,
    *,
    log_id: str,
    conversation_id: str = "",
    kb_id: str = "default",
    question: str = "",
    answer: str = "",
    hit_count: int = 0,
    refs_json: str = "[]",
    retrieval_ms: float = 0.0,
    llm_ms: float = 0.0,
    total_ms: float = 0.0,
) -> QueryLog:
    log = QueryLog(
        id=log_id,
        conversation_id=conversation_id,
        kb_id=kb_id,
        question=question,
        answer=answer,
        hit_count=hit_count,
        refs_json=refs_json,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        total_ms=total_ms,
        created_at=time.time(),
    )
    session.add(log)
    await session.flush()
    return log
