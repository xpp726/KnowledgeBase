"""RAG 编排（services 层）：检索 → 组 prompt → 流式生成 → 绑定引用。

向上只暴露一个异步生成器 ``answer_stream``，按顺序产出类型化事件 dict：

    {"type": "references", "sources": [...], "retrieval_ms": 3.1}
    {"type": "delta", "content": "片段"}          # 多次
    {"type": "done", "answer": "完整答案", "hit_count": 5,
     "retrieval_ms": 3.1, "llm_ms": 4200.0}
    {"type": "error", "message": "..."}           # 异常时

api 层负责把事件编码成 SSE；本模块不 import FastAPI，可脱离 HTTP 单测。

硬规则（开发计划阶段 2 验收）：
- 检索无结果时**不调用 LLM**，直接给固定话术，杜绝幻觉；
- 答案中的 [n] 与 references 的 index 一一对应；
- LLM 并发用信号量限制（config.max_concurrent_requests），超出在生成段排队。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from app.config import get_settings
from app.services.llm import LLMProvider, get_llm
from app.services.retrieval import RetrievalResult, retrieve

logger = logging.getLogger(__name__)
settings = get_settings()

# 部门级单进程：限制同时打到 LLM 的请求数，避免多人并发时人均速度塌陷
_llm_semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

# 检索不到内容时的固定回复（不调用 LLM，避免凭空编造）
NO_HIT_REPLY = (
    "知识库中没有检索到与该问题直接相关的资料，因此无法据此回答。"
    "可以换一种表述，或确认相关文档是否已经上传并完成解析。"
)

SYSTEM_PROMPT = (
    "你是面向企业内部的知识库问答助手，必须严格依据【参考资料】回答用户问题，"
    "并遵守以下规则：\n"
    "1. 只使用参考资料中出现的信息，不得编造资料之外的事实、数据或结论；\n"
    "2. 如果参考资料不足以回答问题，直接说明“根据现有资料无法确定”，不要臆测；\n"
    "3. 引用资料内容时，在相应结论后标注来源编号，例如 [1]、[2][3]；\n"
    "4. 使用简洁、专业的中文回答，条理清晰，必要时分点陈述。"
)


def build_messages(
    question: str,
    context: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """组装发给 LLM 的消息序列：系统规则+资料 → 历史多轮 → 当前问题。"""
    system = f"{SYSTEM_PROMPT}\n\n【参考资料】\n{context}"
    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    return messages


async def answer_stream(
    question: str,
    *,
    kb_id: str | None = None,
    history: list[dict] | None = None,
    mode: str = "dense",
    llm: LLMProvider | None = None,
) -> AsyncIterator[dict]:
    """单个问题的完整 RAG 流式事件流（纯 services，可直接在脚本/测试里消费）。"""
    # ---- 1. 检索 ----
    try:
        result: RetrievalResult = await retrieve(question, kb_id=kb_id, mode=mode)
    except Exception as exc:  # noqa: BLE001
        logger.exception("检索失败")
        yield {"type": "error", "stage": "retrieval", "message": f"检索失败：{exc}"}
        return

    yield {
        "type": "references",
        "sources": result.sources,
        "retrieval_ms": round(result.retrieval_ms, 2),
    }

    # ---- 2. 无命中：不调用 LLM，直接给固定话术 ----
    if not result.has_hits:
        yield {"type": "delta", "content": NO_HIT_REPLY}
        yield {
            "type": "done",
            "answer": NO_HIT_REPLY,
            "hit_count": 0,
            "retrieval_ms": round(result.retrieval_ms, 2),
            "llm_ms": 0.0,
        }
        return

    # ---- 3. 有命中：组 prompt，限流后流式生成 ----
    messages = build_messages(question, result.context, history)
    llm = llm or get_llm()
    answer_parts: list[str] = []
    t0 = time.perf_counter()
    try:
        async with _llm_semaphore:
            async for piece in llm.chat_stream(messages):
                if not piece:
                    continue
                answer_parts.append(piece)
                yield {"type": "delta", "content": piece}
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM 流式生成失败")
        yield {"type": "error", "stage": "llm", "message": f"生成失败：{exc}"}
        return

    llm_ms = (time.perf_counter() - t0) * 1000
    yield {
        "type": "done",
        "answer": "".join(answer_parts),
        "hit_count": len(result.chunks),
        "retrieval_ms": round(result.retrieval_ms, 2),
        "llm_ms": round(llm_ms, 1),
    }
