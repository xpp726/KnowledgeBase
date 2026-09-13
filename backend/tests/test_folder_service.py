"""folder_service 测试：CRUD / 树构建 / 深度限制 / 同名 / 级联删除 / 移动。

每个用例独立 SQLite 库；用 FakeStorage / FakeVectorStore 替代真实外部依赖。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import queries
from app.services import document_service as doc_svc
from app.services import folder_service as folder_svc
from app.services.folder_service import (
    FileNameConflictError,
    FolderDepthLimitError,
    FolderKbMismatchError,
    FolderNameConflictError,
    FolderNotFoundError,
    FolderSystemProtectedError,
)
from tests.fakes import FakeStorage, FakeVectorStore


# ==================== 独立 SQLite 测试库 + 共享 session 上下文 ====================

@pytest.fixture
async def kb_env(monkeypatch):
    """每个用例一个临时 SQLite 库，建表 + 默认 kb + 默认 folder。"""
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

    # 把 service 层用的 get_async_session 都换成临时库
    monkeypatch.setattr(doc_svc, "get_async_session", _fake)
    monkeypatch.setattr(folder_svc, "get_async_session", _fake)

    async with _fake() as s:
        await queries.ensure_knowledge_base(s, "default", name="默认知识库")
        await queries.ensure_default_folder(s, "default", name="默认文件夹")

    yield _fake



# ==================== 建 / 查 / 树 ====================

async def test_ensure_default_folder_idempotent(kb_env):
    f1 = await folder_svc.ensure_default_for_kb("default")
    f2 = await folder_svc.ensure_default_for_kb("default")
    assert f1["folder_id"] == f2["folder_id"]
    assert f1["is_system"] is True


async def test_create_folder_top_level_then_child(kb_env):
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=f1["folder_id"], name="合同")
    assert f1["depth"] == 1 and f2["depth"] == 2
    assert f2["parent_id"] == f1["folder_id"]


async def test_create_folder_depth_limit(kb_env):
    """kb → 顶层 → 子 folder，再创建子 folder 应 FolderDepthLimitError。"""
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=f1["folder_id"], name="B")
    with pytest.raises(FolderDepthLimitError):
        await folder_svc.create_folder(kb_id="default", parent_id=f2["folder_id"], name="C")


async def test_create_folder_same_parent_name_conflict(kb_env):
    await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    with pytest.raises(FolderNameConflictError):
        await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    # 不同 parent 下同名应允许
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="子目录")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=f1["folder_id"], name="研发")
    assert f2["name"] == "研发"


async def test_create_folder_invalid_name(kb_env):
    with pytest.raises(folder_svc.FolderError):
        await folder_svc.create_folder(kb_id="default", parent_id=None, name="")


async def test_create_folder_kb_mismatch(kb_env):
    """parent 属另一个 kb：应 FolderKbMismatchError。"""
    async with kb_env() as s:
        await queries.ensure_knowledge_base(s, "kb_b", name="另一知识库")
        f_other = await queries.create_folder(
            s, kb_id="kb_b", parent_id=None, name="X", depth=1
        )
    with pytest.raises(FolderKbMismatchError):
        await folder_svc.create_folder(
            kb_id="default", parent_id=f_other.folder_id, name="Y"
        )


async def test_folder_tree_structure(kb_env):
    """树构建：folder_tree 应包含 doc_count（直属文件数）。"""
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=f1["folder_id"], name="合同")
    storage = FakeStorage()
    row = await doc_svc.register_document(
        b"x", "a.pdf", kb_id="default", folder_id=f2["folder_id"], storage=storage
    )
    assert row["folder_id"] == f2["folder_id"]

    tree = await folder_svc.get_folder_tree("default")
    top = next((n for n in tree if n["folder_id"] == f1["folder_id"]), None)
    assert top is not None
    assert top["doc_count"] == 0  # f1 直属 0
    assert len(top["children"]) == 1
    sub = top["children"][0]
    assert sub["folder_id"] == f2["folder_id"]
    assert sub["doc_count"] == 1


# ==================== 重命名 ====================

async def test_rename_folder(kb_env):
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="研发")
    renamed = await folder_svc.rename_folder(f1["folder_id"], "R&D")
    assert renamed["name"] == "R&D"


async def test_rename_folder_default_allowed(kb_env):
    """默认 folder 也允许改名（is_system 仅约束删除）。"""
    f = await folder_svc.ensure_default_for_kb("default")
    renamed = await folder_svc.rename_folder(f["folder_id"], "我的文件夹")
    assert renamed["name"] == "我的文件夹"


async def test_rename_folder_conflict(kb_env):
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="B")
    with pytest.raises(FolderNameConflictError):
        await folder_svc.rename_folder(f1["folder_id"], "B")


async def test_rename_folder_not_found(kb_env):
    with pytest.raises(FolderNotFoundError):
        await folder_svc.rename_folder("f_not_exist", "X")


# ==================== 移动 ====================

async def test_move_folder_changes_parent(kb_env):
    f_a = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f_b = await folder_svc.create_folder(kb_id="default", parent_id=None, name="B")
    moved = await folder_svc.move_folder(f_a["folder_id"], f_b["folder_id"])
    assert moved["parent_id"] == f_b["folder_id"]
    assert moved["depth"] == 2


async def test_move_folder_to_root(kb_env):
    f_a = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f_b = await folder_svc.create_folder(kb_id="default", parent_id=None, name="B")
    child = await folder_svc.create_folder(kb_id="default", parent_id=f_a["folder_id"], name="child")
    moved = await folder_svc.move_folder(child["folder_id"], None)
    assert moved["parent_id"] is None
    assert moved["depth"] == 1


async def test_move_folder_self_forbidden(kb_env):
    f_a = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    with pytest.raises(folder_svc.FolderError):
        await folder_svc.move_folder(f_a["folder_id"], f_a["folder_id"])


async def test_move_folder_descendant_forbidden(kb_env):
    """禁止把 folder 移到自身子孙目录下（避免成环）。"""
    f_a = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f_a_child = await folder_svc.create_folder(kb_id="default", parent_id=f_a["folder_id"], name="A_child")
    with pytest.raises(folder_svc.FolderError):
        await folder_svc.move_folder(f_a["folder_id"], f_a_child["folder_id"])


async def test_move_folder_default_forbidden(kb_env):
    """默认 folder 不允许移动。"""
    f = await folder_svc.ensure_default_for_kb("default")
    f_a = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    with pytest.raises(FolderSystemProtectedError):
        await folder_svc.move_folder(f["folder_id"], f_a["folder_id"])


# ==================== 删除 ====================

async def test_delete_folder_empty(kb_env):
    f = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    report = await folder_svc.delete_folder_cascade(f["folder_id"])
    assert report.ok is True
    assert report.deleted_doc_ids == []
    assert f["folder_id"] in report.cascaded_folder_ids


async def test_delete_folder_cascade_with_doc(kb_env, monkeypatch):
    """级联：folder 内有 doc，应一起删（向量 + 文件 + DB）。"""
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    storage = FakeStorage()
    store = FakeVectorStore(hits=[])
    monkeypatch.setattr(doc_svc, "get_storage", lambda: storage)
    monkeypatch.setattr(doc_svc, "get_vectorstore", lambda: store)
    row = await doc_svc.register_document(
        b"x", "del.pdf", kb_id="default", folder_id=f1["folder_id"], storage=storage
    )
    doc_id = row["doc_id"]

    report = await folder_svc.delete_folder_cascade(f1["folder_id"])
    assert report.ok is True
    assert doc_id in report.deleted_doc_ids
    assert (doc_id, "default") in store.deleted
    assert not storage.exists(f"default/{doc_id}/del.pdf")


async def test_delete_folder_protected_default(kb_env):
    """默认 folder 不允许删除。"""
    f = await folder_svc.ensure_default_for_kb("default")
    with pytest.raises(FolderSystemProtectedError):
        await folder_svc.delete_folder_cascade(f["folder_id"])


async def test_delete_folder_not_found(kb_env):
    with pytest.raises(FolderNotFoundError):
        await folder_svc.delete_folder_cascade("f_not_exist")


# ==================== 同名文件（register_document 维度） ====================

async def test_register_document_same_folder_name_rejected(kb_env):
    """同 folder 内同名 file_name：第二次 register 抛 FileNameConflictError。"""
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    storage = FakeStorage()
    r1 = await doc_svc.register_document(
        b"x", "same.pdf", kb_id="default", folder_id=f1["folder_id"], storage=storage
    )
    assert r1["doc_id"]
    with pytest.raises(FileNameConflictError):
        await doc_svc.register_document(
            b"y", "same.pdf", kb_id="default", folder_id=f1["folder_id"], storage=storage
        )


async def test_register_document_different_folder_same_name_allowed(kb_env):
    """跨 folder 同名文件：允许（独立 doc_id）。"""
    f1 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="A")
    f2 = await folder_svc.create_folder(kb_id="default", parent_id=None, name="B")
    storage = FakeStorage()
    r1 = await doc_svc.register_document(
        b"x", "same.pdf", kb_id="default", folder_id=f1["folder_id"], storage=storage
    )
    r2 = await doc_svc.register_document(
        b"x", "same.pdf", kb_id="default", folder_id=f2["folder_id"], storage=storage
    )
    assert r1["doc_id"] != r2["doc_id"]


async def test_register_document_no_folder_auto_default(kb_env):
    """register_document 不传 folder_id 时自动用默认 folder。"""
    storage = FakeStorage()
    row = await doc_svc.register_document(
        b"x", "auto.pdf", kb_id="default", storage=storage
    )
    default = await folder_svc.ensure_default_for_kb("default")
    assert row["folder_id"] == default["folder_id"]