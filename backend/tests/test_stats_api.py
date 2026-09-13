"""数据统计聚合测试：临时库插假 query_logs（kb/general 混合、跨天、带 refs），
验证 cards / trend / top_questions / top_docs / kb_dist 与 mode、days 过滤。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import queries as q


@pytest.fixture
async def session():
    from app.db import async_engine
    maker = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


def refs(*docs: str) -> str:
    return json.dumps([{"doc_name": d} for d in docs], ensure_ascii=False)


async def seed(session):
    now = datetime.now()
    # 今天：2 条 kb（1 命中 1 未命中）、1 条 general
    await q.add_query_log(session, log_id="l1", question="徐州采购候选人", kb_id="default",
                          mode="kb", hit_count=5, refs_json=refs("采购公告.pdf", "公示.pdf"),
                          retrieval_ms=200, llm_ms=1000, total_ms=1300,
                          created_at=now - timedelta(hours=1))
    await q.add_query_log(session, log_id="l2", question="量子力学推导", kb_id="default",
                          mode="kb", hit_count=0, refs_json="[]",
                          retrieval_ms=150, llm_ms=0, total_ms=200,
                          created_at=now - timedelta(minutes=30))
    await q.add_query_log(session, log_id="l3", question="今天天气如何", kb_id="default",
                          mode="general", hit_count=0, refs_json="[]",
                          retrieval_ms=0, llm_ms=500, total_ms=520,
                          created_at=now - timedelta(minutes=15))
    # 3 天前：1 条 kb 命中（同问题重复问）、引用同一文档
    await q.add_query_log(session, log_id="l4", question="徐州采购候选人", kb_id="kb_a",
                          mode="kb", hit_count=3, refs_json=refs("采购公告.pdf"),
                          retrieval_ms=100, llm_ms=800, total_ms=950,
                          created_at=now - timedelta(days=3))
    await session.commit()


async def test_cards_kb_mode(session):
    await seed(session)
    s = await q.stats_summary(session, mode="kb")
    cards = s["cards"]
    assert cards["total"] == 3  # l1/l2/l4（general 排除）
    assert cards["hit_count"] == 2
    assert cards["hit_rate"] == round(2 / 3 * 100, 1)
    assert cards["no_hit_count"] == 1
    assert cards["avg_retrieval_ms"] == round((200 + 150 + 100) / 3, 1)
    assert cards["avg_llm_ms"] == round((1000 + 0 + 800) / 3, 1)


async def test_cards_general_and_all(session):
    await seed(session)
    g = await q.stats_summary(session, mode="general")
    assert g["cards"]["total"] == 1
    assert g["cards"]["hit_count"] == 0
    a = await q.stats_summary(session, mode="all")
    assert a["cards"]["total"] == 4


async def test_trend_pads_days_and_splits_by_day(session):
    await seed(session)
    s = await q.stats_summary(session, mode="kb", days=7)
    # 近 7 天连续补零，最后一天有 2 条、3 天前有 1 条
    assert len(s["trend"]) == 7
    today = s["trend"][-1]
    assert today["count"] == 2
    assert today["hit_rate"] == 50.0
    assert today["avg_total_ms"] == round((1300 + 200) / 2, 1)
    day3 = s["trend"][-4]
    assert day3["count"] == 1
    assert day3["hit_rate"] == 100.0


async def test_days_filter_excludes_old(session):
    await seed(session)
    s = await q.stats_summary(session, mode="kb", days=1)
    assert s["cards"]["total"] == 2  # 3 天前的被排除
    assert len(s["trend"]) == 1
    s2 = await q.stats_summary(session, mode="kb", days=None)
    assert s2["cards"]["total"] == 3  # 全量


async def test_top_questions_and_docs(session):
    await seed(session)
    s = await q.stats_summary(session, mode="kb")
    tq = s["top_questions"]
    assert tq[0]["question"] == "徐州采购候选人"
    assert tq[0]["count"] == 2
    td = s["top_docs"]
    assert td[0]["doc_name"] == "采购公告.pdf"
    assert td[0]["count"] == 2  # 两条问答引用（同问答内多 chunk 只计 1 次）
    assert any(d["doc_name"] == "公示.pdf" for d in td)


async def test_kb_dist(session):
    await seed(session)
    s = await q.stats_summary(session, mode="kb")
    dist = {d["kb_id"]: d["count"] for d in s["kb_dist"]}
    assert dist["default"] == 2
    assert dist["kb_a"] == 1


async def test_empty_db(session):
    s = await q.stats_summary(session, mode="kb")
    assert s["cards"]["total"] == 0
    assert s["cards"]["hit_rate"] == 0.0
    assert s["trend"] == []
    assert s["top_questions"] == []
    assert s["top_docs"] == []
    assert s["kb_dist"] == []
