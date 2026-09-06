"""SSE 流式问答接口。

事件协议（与 docs/开发计划.md 第七节一致，另补一个 meta 事件提前下发会话 id）：

    event: meta         data: {"conversation_id": "...", "is_new": true}
    event: references   data: {"sources": [{"index":1,"doc_name":...,"text":...}]}
    event: delta        data: {"content": "片段"}            # 多次
    event: done         data: {"conversation_id":..., "message_id":...,
                               "hit_count":5, "elapsed":12.3,
                               "retrieval_ms":3.1, "llm_ms":4200.0}
    event: error        data: {"stage":"...", "message":"..."}

api 层只做协议编解码与落库编排，检索/生成/会话规则全部在 services。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.services import conversation_service as conv_svc
from app.services.rag import answer_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 告诉 Nginx 不要缓冲 SSE（部署见开发计划阶段 5）
    "X-Accel-Buffering": "no",
}


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/stream")
async def chat_stream(
    question: str = Query(..., min_length=1, description="用户问题"),
    conversation_id: str | None = Query(None, description="会话 id，留空则新建"),
    kb_id: str | None = Query(None, description="知识库 id，留空用默认库"),
    mode: str = Query("dense", description="问答模式：dense（默认）/ hybrid（知识库检索）/ general（通用问答，不检索）"),
) -> StreamingResponse:
    question = question.strip()
    if mode not in ("dense", "hybrid", "general"):
        mode = "dense"
    conv_mode = "general" if mode == "general" else "kb"

    async def event_gen() -> AsyncIterator[str]:
        t_start = time.perf_counter()
        # 1) 历史必须在写当前 user 消息之前取
        history = await conv_svc.history_for_prompt(conversation_id)
        # 2) 确定会话（新建用问题当标题，会话模式随问答模式）
        conv_id, is_new = await conv_svc.get_or_create_conversation(
            conversation_id, kb_id=kb_id, title=question, mode=conv_mode
        )
        yield _sse("meta", {"conversation_id": conv_id, "is_new": is_new})
        # 3) 落当前问题
        await conv_svc.record_user_message(conv_id, question)

        answer_parts: list[str] = []
        sources: list[dict] = []
        retrieval_ms = 0.0
        llm_ms = 0.0
        hit_count = 0
        errored = False

        # 4) 消费 RAG 事件流并转发
        async for ev in answer_stream(question, kb_id=kb_id, history=history, mode=mode):
            etype = ev.get("type")
            if etype == "references":
                sources = ev.get("sources", [])
                retrieval_ms = float(ev.get("retrieval_ms", 0.0))
                yield _sse("references", {"sources": sources})
            elif etype == "delta":
                piece = ev.get("content", "")
                answer_parts.append(piece)
                yield _sse("delta", {"content": piece})
            elif etype == "done":
                answer_parts = [ev.get("answer", "")]
                hit_count = int(ev.get("hit_count", 0))
                retrieval_ms = float(ev.get("retrieval_ms", retrieval_ms))
                llm_ms = float(ev.get("llm_ms", 0.0))
            elif etype == "error":
                errored = True
                yield _sse("error", {"stage": ev.get("stage"), "message": ev.get("message")})

        # 5) 落答案 + 引用 + 查询日志（出错时不写 assistant 正常回复）
        answer = "".join(answer_parts)
        total_ms = (time.perf_counter() - t_start) * 1000
        message_id = ""
        if not errored and answer:
            message_id = await conv_svc.record_assistant_turn(
                conv_id,
                question,
                answer,
                sources,
                kb_id=kb_id,
                mode=conv_mode,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
            )
        yield _sse(
            "done",
            {
                "conversation_id": conv_id,
                "message_id": message_id,
                "hit_count": hit_count,
                "elapsed": round(total_ms / 1000, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "llm_ms": round(llm_ms, 1),
            },
        )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
