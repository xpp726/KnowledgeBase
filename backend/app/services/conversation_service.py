"""会话业务编排（services 层）：会话获取/创建、多轮历史、消息与查询日志落库。

分层约定：本模块只做业务编排（标题生成、refs 序列化、历史裁剪、同时写
message 与 query_log），具体 ORM 读写收拢在 models/queries.py；不 import FastAPI。

一轮问答的标准时序（由 api/chat 调用）：
    1) history_for_prompt      取旧历史（必须在写当前 user 消息之前）
    2) get_or_create_conversation 确定会话（新建则用问题当标题）
    3) record_user_message     落当前问题
    4) rag.answer_stream       流式生成
    5) record_assistant_turn   落答案 + 引用 + query_log
"""

from __future__ import annotations

import json
import logging
import uuid

from app.config import get_settings
from app.db import get_async_session
from app.models import queries as q

logger = logging.getLogger(__name__)
settings = get_settings()

# 拼进 LLM 的最近消息条数（user+assistant 合计），6 条 ≈ 3 轮
HISTORY_LIMIT = 6


def _id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:24]}"


def _conv_dict(conv) -> dict:
    return {
        "id": conv.id,
        "kb_id": conv.kb_id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }


async def get_or_create_conversation(
    conversation_id: str | None,
    *,
    kb_id: str | None = None,
    title: str = "",
) -> tuple[str, bool]:
    """返回 (conversation_id, is_new)。传入的 id 不存在时也会新建。"""
    kb_id = kb_id or settings.default_kb_id
    async with get_async_session() as session:
        if conversation_id:
            existing = await q.get_conversation(session, conversation_id)
            if existing is not None:
                if title and not existing.title:
                    await q.touch_conversation(session, conversation_id, title)
                return existing.id, False
        conv_id = conversation_id or _id("c_")
        await q.create_conversation(
            session, conv_id, kb_id=kb_id, title=title[:40]
        )
        return conv_id, True


async def history_for_prompt(
    conversation_id: str | None, limit: int = HISTORY_LIMIT
) -> list[dict]:
    """取最近若干条消息的 role/content（正序），供多轮上下文；新会话返回空。"""
    if not conversation_id:
        return []
    async with get_async_session() as session:
        rows = await q.list_messages(session, conversation_id, limit=limit)
        return [{"role": m.role, "content": m.content} for m in rows]


async def record_user_message(conversation_id: str, question: str) -> str:
    async with get_async_session() as session:
        msg = await q.add_message(
            session,
            message_id=_id("m_"),
            conversation_id=conversation_id,
            role="user",
            content=question,
        )
        await q.touch_conversation(session, conversation_id)
        return msg.id


async def record_assistant_turn(
    conversation_id: str,
    question: str,
    answer: str,
    sources: list[dict],
    *,
    kb_id: str | None = None,
    retrieval_ms: float = 0.0,
    llm_ms: float = 0.0,
    total_ms: float = 0.0,
) -> str:
    """同一事务内落 assistant 消息 + query_log（统计报表用）。"""
    refs_json = json.dumps(sources, ensure_ascii=False)
    async with get_async_session() as session:
        msg = await q.add_message(
            session,
            message_id=_id("m_"),
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            refs_json=refs_json,
        )
        await q.add_query_log(
            session,
            log_id=_id("l_"),
            conversation_id=conversation_id,
            kb_id=kb_id or settings.default_kb_id,
            question=question,
            answer=answer,
            hit_count=len(sources),
            refs_json=refs_json,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
            total_ms=total_ms,
        )
        await q.touch_conversation(session, conversation_id)
        return msg.id


# ==================== 会话 CRUD（供 api/conversation） ====================

async def list_conversations(kb_id: str | None = None) -> list[dict]:
    async with get_async_session() as session:
        rows = await q.list_conversations(session, kb_id)
        return [_conv_dict(c) for c in rows]


async def conversation_messages(conversation_id: str) -> list[dict]:
    """完整消息详情（refs 解析回列表），供前端还原一次会话。"""
    async with get_async_session() as session:
        rows = await q.list_messages(session, conversation_id)
        out = []
        for m in rows:
            try:
                refs = json.loads(m.refs_json) if m.refs_json else []
            except json.JSONDecodeError:
                refs = []
            out.append(
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role,
                    "content": m.content,
                    "refs": refs,
                    "created_at": m.created_at,
                }
            )
        return out


async def remove_conversation(conversation_id: str) -> None:
    async with get_async_session() as session:
        await q.delete_conversation_rows(session, conversation_id)


async def rename_conversation(conversation_id: str, title: str) -> dict | None:
    """改名：覆盖标题并刷新 updated_at。会话不存在返回 None（api 层映射 404）。"""
    title = title.strip()
    if not title:
        raise ValueError("标题不能为空")
    async with get_async_session() as session:
        conv = await q.rename_conversation(session, conversation_id, title)
        return _conv_dict(conv) if conv is not None else None
