"""retrieval 检索编排单测：纯函数过滤逻辑 + Fake 替身的 retrieve 主流程，不连真实 Milvus。"""

from __future__ import annotations

import pytest

from app.services.retrieval import (
    RetrievalResult,
    RetrievedChunk,
    _fingerprint,
    _hits_to_chunks,
    build_context,
    retrieve,
)
from tests.fakes import FakeEmbedder, FakeVectorStore, make_hit


# ---------- _fingerprint ----------

def test_fingerprint_removes_space_and_pipe():
    assert _fingerprint("|甲 乙| 丙") == "甲乙丙"
    assert _fingerprint("一二三四五六七八九十", width=4) == "一二三四"


# ---------- _hits_to_chunks ----------

def test_score_threshold_filters_low():
    hits = [
        make_hit("a", text="甲公司中标第一包段的相关内容", score=0.80),
        make_hit("b", text="乙公司无关的低分内容片段文字", score=0.40),  # 低于 0.55
        make_hit("c", text="丙公司高分的另一段不同正文内容", score=0.60),
    ]
    out = _hits_to_chunks(hits, top_n=10, score_threshold=0.55, max_chars=10000)
    assert [c.chunk_id for c in out] == ["a", "c"]


def test_chunk_id_dedup():
    hits = [make_hit("same", text="内容一"), make_hit("same", text="内容二")]
    out = _hits_to_chunks(hits, top_n=10, score_threshold=0.0, max_chars=10000)
    assert len(out) == 1


def test_near_duplicate_folded():
    hits = [
        make_hit("a", text="成交候选人公示名单"),
        make_hit("b", text="成交 候选人 | 公示名单"),  # 仅空白/竖线差异
    ]
    out = _hits_to_chunks(hits, top_n=10, score_threshold=0.0, max_chars=10000)
    assert len(out) == 1 and out[0].chunk_id == "a"


def test_top_n_limit():
    hits = [make_hit(f"c{i}", text=f"彼此不同的第{i}段正文内容", score=0.9) for i in range(5)]
    out = _hits_to_chunks(hits, top_n=2, score_threshold=0.0, max_chars=10000)
    assert len(out) == 2


def test_char_budget_truncates():
    hits = [
        make_hit("a", text="甲" * 10, score=0.9),
        make_hit("b", text="乙" * 100, score=0.9),
    ]
    out = _hits_to_chunks(hits, top_n=10, score_threshold=0.0, max_chars=30)
    assert len(out) == 2
    assert len(out[0].text) == 10
    assert len(out[1].text) == 20  # 剩余预算 30-10=20，超长截断


def test_index_starts_at_one_and_source_shape():
    hits = [
        make_hit("a", text="第一段彼此不同的正文内容", score=0.9),
        make_hit("b", text="第二段彼此不同的正文内容", score=0.9),
    ]
    out = _hits_to_chunks(hits, top_n=10, score_threshold=0.0, max_chars=10000)
    assert [c.index for c in out] == [1, 2]
    src = out[0].to_source()
    assert set(src) == {"index", "chunk_id", "doc_id", "doc_name", "page", "score", "text"}


# ---------- build_context ----------

def test_build_context_numbered_and_paged():
    chunks = [
        RetrievedChunk(1, "c1", "d1", "招标文件.pdf", "正文甲", 3, 0.8),
        RetrievedChunk(2, "c2", "d1", "招标文件.pdf", "正文乙", 0, 0.7),
    ]
    ctx = build_context(chunks)
    assert "[1]" in ctx and "招标文件.pdf（第 3 页）" in ctx and "正文甲" in ctx
    assert "[2]" in ctx and "正文乙" in ctx


def test_build_context_empty():
    assert build_context([]) == ""


# ---------- retrieve 主流程（Fake） ----------

async def test_retrieve_dense_route_passes_kb_id():
    hits = [
        make_hit("a", text="第一段命中的正文内容", score=0.8),
        make_hit("b", text="第二段命中的正文内容", score=0.7),
    ]
    emb, store = FakeEmbedder(), FakeVectorStore(hits)
    result = await retrieve("问题", kb_id="kb7", mode="dense", embedder=emb, store=store)
    assert store.calls[0][0] == "dense"
    assert store.calls[0][2] == "kb7"  # kb_id 透传到向量库
    assert emb.last_query == "问题"
    assert result.has_hits and len(result.sources) == 2
    assert result.retrieval_ms >= 0 and result.mode == "dense"


async def test_retrieve_hybrid_route():
    store = FakeVectorStore([make_hit("a", score=0.9)])
    result = await retrieve("问题", mode="hybrid", embedder=FakeEmbedder(), store=store)
    assert store.calls[0][0] == "hybrid"
    assert result.has_hits


async def test_retrieve_no_hit_when_all_below_threshold():
    store = FakeVectorStore([make_hit("a", score=0.30), make_hit("b", score=0.40)])
    result = await retrieve("无关问题", embedder=FakeEmbedder(), store=store)
    assert isinstance(result, RetrievalResult)
    assert not result.has_hits and result.context == "" and result.sources == []
