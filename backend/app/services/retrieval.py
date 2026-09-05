"""检索编排（services 层）：问题 → 向量召回 → 过滤截断 → 上下文与引用。

职责边界：
- 向上（rag / api）屏蔽 embedding + Milvus 的调用细节，只暴露 ``retrieve``。
- 不 import FastAPI、不碰 HTTP 协议；pymilvus / httpx 均为同步阻塞，统一丢线程池。

检索路线（依据 docs/阶段1验证报告.md 实测结论）：
- 小语料 + 强 dense 模型下 dense 单路 Recall@5=100%、MRR=88.3%，
  hybrid(RRF) 反被弱 sparse 拖到 MRR=64.5%，故 **默认 mode="dense"**；
  "hybrid" 作为可选项保留，供二期精确词匹配场景开启。
- 召回 ``milvus_top_k``（默认 30）条候选，再按分数取前 ``rerank_top_n``
  （当前无 reranker，等价于按相似度截断；二期接 rerank 只改这一层）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.services.embedding import EmbeddingClient, get_embedder
from app.services.vectorstore import Hit, VectorStore, get_vectorstore

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RetrievedChunk:
    """进入上下文的一条片段，index 从 1 开始，与正文 [n] 引用对应。"""

    index: int
    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int
    score: float
    kb_id: str = "default"

    def to_source(self) -> dict:
        """转成 SSE references 事件 / 消息 refs 用的纯字典。"""
        return {
            "index": self.index,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "page": self.page,
            "score": round(self.score, 4),
            "text": self.text,
        }


@dataclass
class RetrievalResult:
    question: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    retrieval_ms: float = 0.0
    mode: str = "dense"

    @property
    def has_hits(self) -> bool:
        return bool(self.chunks)

    @property
    def sources(self) -> list[dict]:
        return [c.to_source() for c in self.chunks]


def _fingerprint(text: str, width: int = 40) -> str:
    """近重复指纹：去掉空白与表格竖线后取前若干字。

    表格解析会产生大量仅含标题行的近似 chunk（如 ``|XX公示||||``），
    它们 chunk_id 不同但内容几乎一致，会挤占 top_n，用前缀指纹折叠掉。
    """
    return re.sub(r"[\s|]+", "", text)[:width]


def _hits_to_chunks(
    hits: list[Hit],
    *,
    top_n: int,
    score_threshold: float,
    max_chars: int,
) -> list[RetrievedChunk]:
    """阈值过滤 → chunk_id 去重 → 近重复折叠 → 取前 N → 按字符预算截断 → 编号。"""
    seen: set[str] = set()
    fingerprints: set[str] = set()
    picked: list[RetrievedChunk] = []
    budget = max_chars
    for hit in hits:
        if len(picked) >= top_n:
            break
        if hit.score < score_threshold:
            continue
        if not hit.chunk_id or hit.chunk_id in seen:
            continue
        text = hit.text.strip()
        if not text:
            continue
        fp = _fingerprint(text)
        if fp and fp in fingerprints:
            continue
        seen.add(hit.chunk_id)
        # 上下文总长度按字符预算粗控（中文约 1 字 ≈ 1 token），单段最多用掉剩余额度
        if budget <= 0:
            break
        if len(text) > budget:
            text = text[:budget]
        budget -= len(text)
        fingerprints.add(fp)
        picked.append(
            RetrievedChunk(
                index=len(picked) + 1,
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                doc_name=hit.doc_name,
                text=text,
                page=hit.page,
                score=hit.score,
                kb_id=hit.kb_id,
            )
        )
    return picked


def build_context(chunks: list[RetrievedChunk]) -> str:
    """把片段拼成带编号的上下文纯文本（无片段时返回空串）。"""
    blocks: list[str] = []
    for c in chunks:
        page_hint = f"（第 {c.page} 页）" if c.page else ""
        blocks.append(f"[{c.index}] 来源文档：{c.doc_name}{page_hint}\n{c.text}")
    return "\n\n".join(blocks)


async def retrieve(
    question: str,
    *,
    kb_id: str | None = None,
    mode: str = "dense",
    recall: int | None = None,
    top_n: int | None = None,
    score_threshold: float | None = None,
    max_context_chars: int | None = None,
    embedder: EmbeddingClient | None = None,
    store: VectorStore | None = None,
) -> RetrievalResult:
    """检索主入口。

    参数:
        question: 用户问题（当前轮）。
        kb_id: 知识库过滤；None 表示跨库检索。
        mode: "dense"（默认）/ "hybrid"（dense+sparse RRF）。
        recall: Milvus 候选召回条数，默认 milvus_top_k。
        top_n: 最终进入上下文的片段数，默认 rerank_top_n。
        score_threshold: 相似度下限，默认配置 score_threshold。
        max_context_chars: 上下文总字符预算，默认 max_context_tokens。
    """
    embedder = embedder or get_embedder()
    store = store or get_vectorstore()
    recall = recall or settings.milvus_top_k
    top_n = top_n or settings.rerank_top_n
    if score_threshold is None:
        score_threshold = settings.score_threshold
    max_context_chars = max_context_chars or settings.max_context_tokens

    t0 = time.perf_counter()
    dense, sparse = await embedder.embed_query(question)

    if mode == "hybrid":
        hits = await asyncio.to_thread(
            store.hybrid_search, dense, sparse, recall, kb_id
        )
    else:
        hits = await asyncio.to_thread(store.dense_search, dense, recall, kb_id)

    chunks = _hits_to_chunks(
        hits,
        top_n=top_n,
        score_threshold=score_threshold,
        max_chars=max_context_chars,
    )
    context = build_context(chunks)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if not chunks:
        logger.info("检索无命中（kb_id=%s, mode=%s）：%s", kb_id, mode, question[:60])
    else:
        logger.info(
            "检索命中 %d 段（候选 %d，top 分数 %.4f，%.1fms）",
            len(chunks), len(hits), chunks[0].score, elapsed_ms,
        )

    return RetrievalResult(
        question=question,
        chunks=chunks,
        context=context,
        retrieval_ms=elapsed_ms,
        mode=mode,
    )
