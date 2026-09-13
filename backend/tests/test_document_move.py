"""document_service.move_documents 测试：同 kb 移动 / 同名拒绝 / 跨 kb 拒绝 / 幂等 / 错误隔离。

复用 test_folder_service 的"独立临时 SQLite + 替换 get_async_session"模式，离线可重复。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import queries
from app.services import document_service as doc_svc
from app.services import folder_service as folder_svc
from app.services.folder_service import FolderNotFoundError
from tests.fakes import FakeStorage


@pytest.fixture
async def move_env(monkeypatch):
    """每个用例一个临时 SQLite 库，建表 + 两个 kb（default / kb2，各带默认 folder）。"""
    from app.db import async_engine

    maker = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager
    async def _fake():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    monkeypatch.setattr(doc_svc, "get_async_session", _fake)
    monkeypatch.setattr(folder_svc, "get_async_session", _fake)

    async with _fake() as s:
        await queries.ensure_knowledge_base(s, "default", name="默认知识库")
        await queries.ensure_knowledge_base(s, "kb2", name="研发库")
        await queries.ensure_default_folder(s, "default", name="默认文件夹")
        await queries.ensure_default_folder(s, "kb2", name="研发默认")

    yield _fake



async def _make_doc(
    file_name: str, *, kb_id: str = "default", folder_id: str | None = None
) -> str:
    """经 register_document 登记一个 pending 文档（FakeStorage 落盘），返回 doc_id。"""
    row = await doc_svc.register_document(
        b"hello", file_name, kb_id=kb_id, folder_id=folder_id, storage=FakeStorage()
    )
    return row["doc_id"]


async def _default_folder_id(move_env, kb_id: str) -> str:
    async with move_env() as s:
        f = await queries.get_default_folder(s, kb_id)
        assert f is not None
        return f.folder_id


# ==================== 成功路径 ====================

async def test_move_documents_updates_folder_id(move_env):
    target = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    doc_id = await _make_doc("a.pdf")  # 落在默认 folder
    res = await doc_svc.move_documents([doc_id], target["folder_id"])
    assert res == [{"doc_id": doc_id, "status": "moved"}]
    async with move_env() as s:
        doc = await queries.get_document(s, doc_id)
        assert doc.folder_id == target["folder_id"]


async def test_move_documents_already_in_target_idempotent(move_env):
    doc_id = await _make_doc("a.pdf")
    def_id = await _default_folder_id(move_env, "default")
    res = await doc_svc.move_documents([doc_id], def_id)
    assert res[0]["status"] == "moved"  # 已在目标 folder：幂等成功，不报错


async def test_move_documents_multi_docs_same_target(move_env):
    target = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    d1 = await _make_doc("a.pdf")
    d2 = await _make_doc("b.pdf")
    res = await doc_svc.move_documents([d1, d2], target["folder_id"])
    assert all(r["status"] == "moved" for r in res)
    async with move_env() as s:
        for doc_id in (d1, d2):
            doc = await queries.get_document(s, doc_id)
            assert doc.folder_id == target["folder_id"]


# ==================== 失败路径 ====================

async def test_move_documents_target_folder_missing(move_env):
    doc_id = await _make_doc("a.pdf")
    with pytest.raises(FolderNotFoundError):
        await doc_svc.move_documents([doc_id], "f_nope")


async def test_move_documents_same_name_rejected(move_env):
    target = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    await _make_doc("a.pdf", folder_id=target["folder_id"])  # 目标已有同名
    doc_id = await _make_doc("a.pdf")  # 默认 folder 里的同名文档
    res = await doc_svc.move_documents([doc_id], target["folder_id"])
    assert res[0]["status"] == "rejected"
    assert "同名" in res[0]["error"]
    # 原位置不动
    async with move_env() as s:
        doc = await queries.get_document(s, doc_id)
        assert doc.folder_id != target["folder_id"]


async def test_move_documents_cross_kb_rejected(move_env):
    doc_id = await _make_doc("a.pdf", kb_id="default")
    kb2_id = await _default_folder_id(move_env, "kb2")
    res = await doc_svc.move_documents([doc_id], kb2_id)
    assert res[0]["status"] == "rejected"
    assert "跨知识库" in res[0]["error"]
    # 文档归属不变
    async with move_env() as s:
        doc = await queries.get_document(s, doc_id)
        def_id = await _default_folder_id(move_env, "default")
        assert doc.folder_id == def_id


async def test_move_documents_partial_failure_isolated(move_env):
    """批量：一个不存在 + 一个正常 → 逐文件错误隔离，不互相阻塞。"""
    target = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    doc_id = await _make_doc("a.pdf")
    res = await doc_svc.move_documents([doc_id, "ghost_id"], target["folder_id"])
    by_id = {r["doc_id"]: r for r in res}
    assert by_id[doc_id]["status"] == "moved"
    assert by_id["ghost_id"]["status"] == "rejected"
    assert "不存在" in by_id["ghost_id"]["error"]
