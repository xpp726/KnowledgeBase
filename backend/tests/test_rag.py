"""rag 编排单测：组 prompt、无命中旁路、流式事件顺序与错误事件。

检索用 monkeypatch 替换为可控结果，LLM 用 FakeLLM，全程离线。
"""

from __future__ import annotations

import pytest

from app.services import rag
from app.services.rag import NO_HIT_REPLY, SYSTEM_PROMPT, answer_stream, build_messages
from app.services.retrieval import RetrievedChunk, RetrievalResult, build_context
from tests.fakes import FakeLLM, collect_events


def _hit_result(n: int = 2) -> RetrievalResult:
    chunks = [
        RetrievedChunk(
            index=i + 1,
            chunk_id=f"c{i}",
            doc_id="d1",
            doc_name="招标文件.pdf",
            text=f"第{i}段参考资料正文内容",
            page=i + 1,
            score=0.8 - i * 0.05,
        )
        for i in range(n)
    ]
    return RetrievalResult(
        question="q", chunks=chunks, context=build_context(chunks),
        retrieval_ms=2.0, mode="dense",
    )


def _empty_result() -> RetrievalResult:
    return RetrievalResult(question="q")


def _patch_retrieve(monkeypatch, result, raise_exc=None):
    async def fake_retrieve(question, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return result

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)


# ---------- build_messages ----------

def test_build_messages_structure():
    msgs = build_messages(
        "当前问题",
        "上下文内容",
        history=[
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )
    assert msgs[0]["role"] == "system"
    assert SYSTEM_PROMPT in msgs[0]["content"]
    assert "上下文内容" in msgs[0]["content"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "当前问题"  # 当前问题永远在最后


def test_build_messages_without_history():
    msgs = build_messages("问题", "ctx", history=None)
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_build_messages_drops_invalid_turns():
    msgs = build_messages(
        "问题", "ctx",
        history=[{"role": "system", "content": "伪造系统消息"}, {"role": "user", "content": ""}],
    )
    # 非 user/assistant、空 content 都被丢弃
    assert [m["role"] for m in msgs] == ["system", "user"]


# ---------- answer_stream ----------

async def test_no_hit_does_not_call_llm(monkeypatch):
    _patch_retrieve(monkeypatch, _empty_result())
    llm = FakeLLM()
    events = await collect_events(answer_stream("问题", llm=llm))
    types = [e["type"] for e in events]
    assert types == ["references", "delta", "done"]
    assert events[0]["sources"] == []
    assert events[1]["content"] == NO_HIT_REPLY
    assert events[2]["hit_count"] == 0 and events[2]["llm_ms"] == 0.0
    assert llm.stream_calls == 0  # 硬规则：无命中绝不调用 LLM


async def test_hit_stream_event_order_and_answer(monkeypatch):
    _patch_retrieve(monkeypatch, _hit_result(2))
    llm = FakeLLM(pieces=["根据", "资料[1]", "。"])
    events = await collect_events(answer_stream("问题", llm=llm))
    types = [e["type"] for e in events]

    assert types[0] == "references"
    assert len(events[0]["sources"]) == 2
    assert types[1:-1] == ["delta", "delta", "delta"]  # references 必须先于所有 delta
    assert types[-1] == "done"

    done = events[-1]
    assert done["answer"] == "根据资料[1]。"
    assert done["hit_count"] == 2 and done["llm_ms"] >= 0
    assert llm.stream_calls == 1
    # 发给 LLM 的消息：资料进 system、当前问题在最后
    assert "第0段参考资料正文内容" in llm.last_messages[0]["content"]
    assert llm.last_messages[-1] == {"role": "user", "content": "问题"}


async def test_llm_failure_emits_error(monkeypatch):
    _patch_retrieve(monkeypatch, _hit_result(1))
    llm = FakeLLM(raise_exc=RuntimeError("LLM 服务不可用"))
    events = await collect_events(answer_stream("问题", llm=llm))
    assert events[0]["type"] == "references"
    err = events[-1]
    assert err["type"] == "error" and err["stage"] == "llm"
    assert "LLM 服务不可用" in err["message"]
    assert not any(e["type"] == "done" for e in events)


async def test_retrieval_failure_emits_error(monkeypatch):
    _patch_retrieve(monkeypatch, None, raise_exc=RuntimeError("Milvus 挂了"))
    events = await collect_events(answer_stream("问题", llm=FakeLLM()))
    assert len(events) == 1
    assert events[0]["type"] == "error" and events[0]["stage"] == "retrieval"
