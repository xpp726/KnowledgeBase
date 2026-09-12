"""文档管理 + 知识库：分页/搜索/筛选、登记（duplicated）、删除补偿、kb 查询。

使用独立临时 sqlite（pytest tmp_path）+ FakeStorage/FakeVectorStore，
不连接真实 kb.db / MinIO / Milvus，离线可重复。
"""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models import queries as q
from app.services import document_service as svc
from app.services.folder_service import FileNameConflictError
from app.services.ingestion import make_doc_id
from tests.fakes import FakeStorage, FakeVectorStore


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/doc_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


# ==================== 知识库 ====================

async def test_create_and_list_knowledge_bases(session):
    await q.create_knowledge_base(session, "kb_1", name="研发资料", description="d")
    await q.create_knowledge_base(session, "kb_2", name="市场资料")
    await session.commit()

    rows = await q.list_knowledge_bases(session)
    assert [r.kb_id for r in rows] == ["kb_1", "kb_2"]
    assert rows[0].name == "研发资料"


async def test_ensure_knowledge_base_idempotent(session):
    # 首次创建
    kb = await q.ensure_knowledge_base(session, "default", name="默认知识库")
    assert kb.kb_id == "default"
    assert kb.name == "默认知识库"
    # 再次调用幂等：不重复、不报错、不覆盖已有记录
    kb2 = await q.ensure_knowledge_base(session, "default", name="默认知识库")
    assert kb2.kb_id == "default"
    await session.commit()

    rows = await q.list_knowledge_bases(session)
    assert len(rows) == 1


async def test_count_documents_by_kb(session):
    await q.upsert_document(session, doc_id="d1", kb_id="kb_1", file_name="a.pdf", status="done")
    await q.upsert_document(session, doc_id="d2", kb_id="kb_1", file_name="b.pdf", status="failed")
    await q.upsert_document(session, doc_id="d3", kb_id="kb_2", file_name="c.pdf", status="done")
    await session.commit()

    counts = await q.count_documents_by_kb(session)
    assert counts == {"kb_1": 2, "kb_2": 1}


# ==================== 分页 / 搜索 / 筛选 ====================

async def _seed_docs(session) -> None:
    for i, name in enumerate(["招标公告.pdf", "中标公示.pdf", "技术方案.docx", "会议纪要.md", "合同模板.xlsx"]):
        await q.upsert_document(
            session,
            doc_id=f"d{i}",
            kb_id="kb_1",
            file_name=name,
            status="done" if i % 2 == 0 else "failed",
        )
    await session.commit()


async def test_paginate_basic(session):
    await _seed_docs(session)
    items, total = await q.paginate_documents(session, kb_id="kb_1", page=1, page_size=2)
    assert total == 5
    assert len(items) == 2  # 按 updated_at desc


async def test_paginate_search_and_status(session):
    await _seed_docs(session)
    # "中标公示.pdf" 在种子中为 failed（i%2==1）
    items, total = await q.paginate_documents(session, kb_id="kb_1", search="公示", status="failed")
    assert total == 1
    assert items[0].file_name == "中标公示.pdf"

    # 只按状态
    items, total = await q.paginate_documents(session, status="failed")
    assert total == 2
    # 只按搜索
    items, total = await q.paginate_documents(session, search="技术")
    assert total == 1


async def test_paginate_empty(session):
    items, total = await q.paginate_documents(session, kb_id="nope")
    assert total == 0 and items == []


def _make_fake_session(maker):
    """模拟 app.db.get_async_session：退出时 commit，异常回滚。"""

    @asynccontextmanager
    async def fake_session():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    return fake_session

# 说明：register_document 内部使用 document_service 模块导入的 get_async_session
# （from app.db import ... 模块级绑定），测试通过 monkeypatch 替换 svc.get_async_session
# 为临时库，避免触达真实 kb.db。

async def test_register_duplicated_flag(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/reg_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(svc, "get_async_session", _make_fake_session(maker))

    storage = FakeStorage()
    row1 = await svc.register_document(b"x" * 10, "同名.pdf", kb_id="kb_y", storage=storage)
    assert row1["duplicated"] is False

    # 第二次同名登记（folder 内同名拒绝）：FileNameConflictError
    with pytest.raises(FileNameConflictError):
        await svc.register_document(b"x" * 10, "同名.pdf", kb_id="kb_y", storage=storage)
    await engine.dispose()


# ==================== 删除补偿 ====================

async def test_delete_document_compensation(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/del_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(svc, "get_async_session", _make_fake_session(maker))

    storage = FakeStorage()
    store = FakeVectorStore(hits=[])
    row = await svc.register_document(b"data", "待删除.pdf", kb_id="kb_z", storage=storage)
    doc_id = row["doc_id"]

    report = await svc.delete_document(doc_id, store=store, storage=storage)
    assert report.ok is True
    assert report.db_deleted is True
    assert report.file_deleted is True
    assert store.deleted == [(doc_id, "kb_z")]
    assert not storage.exists(f"kb_z/{doc_id}/待删除.pdf")
    # 账本已删，重复删除幂等
    report2 = await svc.delete_document(doc_id, store=store, storage=storage)
    assert report2.found is False and report2.ok is True
    await engine.dispose()


async def test_delete_document_vector_failure_keeps_ledger(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/del2_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(svc, "get_async_session", _make_fake_session(maker))

    storage = FakeStorage()
    row = await svc.register_document(b"data", "删失败.pdf", kb_id="kb_z", storage=storage)
    doc_id = row["doc_id"]

    class BrokenStore:
        def delete_by_doc(self, doc_id, kb_id="default"):
            raise RuntimeError("Milvus 挂了")

    report = await svc.delete_document(doc_id, store=BrokenStore(), storage=storage)
    assert report.ok is False
    assert report.vector_deleted == 0
    assert "vector" in report.errors[0]
    # 账本保留（DB 未删），可重跑
    async with maker() as s:
        assert await q.get_document(s, doc_id) is not None
    await engine.dispose()


# ==================== reprocess 链路 doc_id 一致性 ====================

async def test_reprocess_propagates_doc_id_to_ingest_bytes(tmp_path, monkeypatch):
    """reprocess(doc_id) → process_bytes → ingest_bytes 必须用同一 doc_id，
    否则 chunks / status 会写到错的 Document 行（重算出来与 register 时不一致的 hash）。
    这是 2026-09-08「同名上传后 done 那条 doc 与 pending 那条 doc_id 不同」的回归。
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/reproc_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(svc, "get_async_session", _make_fake_session(maker))

    storage = FakeStorage()
    # folder_id 留 None → 走 ensure_default_folder，无需预建 folder
    row = await svc.register_document(b"data", "同.pdf", kb_id="kb_r", storage=storage)
    expected_doc_id = row["doc_id"]

    # 抓 ingest_bytes 调用，断言它收到的 doc_id == register 的 doc_id
    captured: dict = {}

    async def fake_ingest_bytes(data, file_name, **kw):
        captured["doc_id"] = kw.get("doc_id")
        captured["folder_id"] = kw.get("folder_id")
        return svc.IngestResult(file_name=file_name, doc_id=kw.get("doc_id"), kb_id="kb_r", status="done", elapsed=0, chunks=0)

    monkeypatch.setattr(svc, "ingest_bytes", fake_ingest_bytes)
    # fake_storage.get 也走 fake
    await svc.reprocess(expected_doc_id, storage=storage)

    assert captured["doc_id"] == expected_doc_id, (
        f"reprocess 透传给 ingest_bytes 的 doc_id 必须等于 register 的 doc_id；"
        f" 否则 ingest 的 chunks/status 写到另一 Document 行，"
        f"导致「后端显示 done，但前端这条 doc 还显示 pending」。"
    )
    await engine.dispose()


async def test_mark_document_queued_sets_pending_and_idempotent(tmp_path, monkeypatch):
    """reprocess 调度前 mark_document_queued：终态 → pending（排队中），幂等。

    这是「第三个及之后点击重试/重新解析时页面状态不变」的回归防护：
    解析并发信号量排队期间，文档必须立即可见为 pending，前端轮询才会持续刷新。
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/queued_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(svc, "get_async_session", _make_fake_session(maker))

    async with maker() as s:
        await q.upsert_document(s, doc_id="d_q", kb_id="kb_q", file_name="q.pdf", status="failed")
        await s.commit()

    # failed → pending
    await svc.mark_document_queued("d_q")
    async with maker() as s:
        assert await q.document_status(s, "d_q") == "pending"

    # 幂等：pending → pending 不抛错、不重复推进
    await svc.mark_document_queued("d_q")
    async with maker() as s:
        assert await q.document_status(s, "d_q") == "pending"

    # done → pending 同样合法（重新解析场景）
    async with maker() as s:
        await q.upsert_document(s, doc_id="d_q2", kb_id="kb_q", file_name="q2.pdf", status="done")
        await s.commit()
    await svc.mark_document_queued("d_q2")
    async with maker() as s:
        assert await q.document_status(s, "d_q2") == "pending"

    # 文档不存在：静默跳过，不抛错
    await svc.mark_document_queued("nope")

    await engine.dispose()
