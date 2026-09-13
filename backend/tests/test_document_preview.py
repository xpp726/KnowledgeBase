"""预览/下载 API 测试：PDF/图片/TXT 预览、docx 415、下载文件名编码、权限与 404。

复用 test_document_move 的"独立临时 SQLite + monkeypatch doc_svc"模式；
HTTP 层用 TestClient(main_app)，登录走 conftest 的 test_kb.db 默认 admin。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app as main_app
from app.models import queries as q
from app.services import document_service as doc_svc
from tests.fakes import FakeStorage


@pytest.fixture
async def doc_env(monkeypatch):
    """临时库建表 + 建 kb/folder；monkeypatch doc_svc 的 session 与 storage。"""
    from app.db import async_engine
    maker = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

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

    storage = FakeStorage()
    monkeypatch.setattr(doc_svc, "get_storage", lambda: storage)

    async with _fake() as s:
        await q.ensure_knowledge_base(s, "default", name="默认知识库")
        await q.ensure_default_folder(s, "default", name="默认文件夹")

    yield _fake, storage


async def _seed_doc(doc_env, doc_id: str, file_name: str, data: bytes) -> None:
    """登记文档 + 把原始文件放入 FakeStorage（key 形如 {kb_id}/{doc_id}/{file_name}）。"""
    ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    key = f"default/{doc_id}/{file_name}"
    async with doc_env[0]() as s:
        await q.upsert_document(
            s,
            doc_id=doc_id,
            kb_id="default",
            file_name=file_name,
            file_path=key,
            file_ext=ext,
            file_size=len(data),
            status="done",
        )
    doc_env[1].put(key, data)


def _client() -> tuple[TestClient, dict]:
    client = TestClient(main_app)
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return client, {"Authorization": f"Bearer {r.json()['token']}"}


# ==================== 预览 ====================

async def test_preview_pdf(doc_env):
    await _seed_doc(doc_env, "d_pdf", "招标公告.pdf", b"%PDF-1.4 fake pdf bytes")
    client, headers = _client()
    r = client.get("/api/documents/d_pdf/preview", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == b"%PDF-1.4 fake pdf bytes"


async def test_preview_txt(doc_env):
    await _seed_doc(doc_env, "d_txt", "说明.txt", "你好，知识库".encode("utf-8"))
    client, headers = _client()
    r = client.get("/api/documents/d_txt/preview", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.content == "你好，知识库".encode("utf-8")


async def test_preview_image(doc_env):
    await _seed_doc(doc_env, "d_img", "截图.png", b"\x89PNG\r\n\x1a\nfake")
    client, headers = _client()
    r = client.get("/api/documents/d_img/preview", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == b"\x89PNG\r\n\x1a\nfake"


async def test_preview_docx_unsupported_415(doc_env):
    await _seed_doc(doc_env, "d_docx", "方案.docx", b"PK fake docx")
    client, headers = _client()
    r = client.get("/api/documents/d_docx/preview", headers=headers)
    assert r.status_code == 415


async def test_preview_doc_not_found(doc_env):
    client, headers = _client()
    r = client.get("/api/documents/no_such_doc/preview", headers=headers)
    assert r.status_code == 404


async def test_preview_file_missing_404(doc_env):
    # 文档记录存在但原始文件缺失（FakeStorage 无对应 key）
    async with doc_env[0]() as s:
        await q.upsert_document(
            s,
            doc_id="d_missing",
            kb_id="default",
            file_name="丢失.pdf",
            file_path="default/d_missing/丢失.pdf",
            file_ext=".pdf",
            file_size=10,
            status="done",
        )
    client, headers = _client()
    r = client.get("/api/documents/d_missing/preview", headers=headers)
    assert r.status_code == 404


# ==================== 下载 ====================

async def test_download_returns_file_with_original_name(doc_env):
    await _seed_doc(doc_env, "d_down", "国网河南招标.pdf", b"%PDF-1.4 download bytes")
    client, headers = _client()
    r = client.get("/api/documents/d_down/download", headers=headers)
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 download bytes"
    # Content-Disposition 用 RFC 5987 编码原始文件名（兼容中文）
    disp = r.headers["content-disposition"]
    assert "attachment" in disp
    from urllib.parse import unquote

    assert "国网河南招标.pdf" in unquote(disp)


async def test_download_works_for_docx(doc_env):
    # docx 不支持预览，但下载不受影响
    await _seed_doc(doc_env, "d_dx", "方案.docx", b"PK fake docx")
    client, headers = _client()
    r = client.get("/api/documents/d_dx/download", headers=headers)
    assert r.status_code == 200
    assert r.content == b"PK fake docx"


# ==================== 权限 ====================

async def test_preview_requires_auth(doc_env):
    await _seed_doc(doc_env, "d_auth", "a.pdf", b"%PDF auth")
    client, _ = _client()
    r = client.get("/api/documents/d_auth/preview")
    assert r.status_code == 401


async def test_download_requires_auth(doc_env):
    await _seed_doc(doc_env, "d_auth2", "a.pdf", b"%PDF auth")
    client, _ = _client()
    r = client.get("/api/documents/d_auth2/download")
    assert r.status_code == 401
