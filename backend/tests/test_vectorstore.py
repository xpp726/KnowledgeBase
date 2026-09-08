"""真实 VectorStore 行为的单元测试：用 monkeypatch 替身 MilvusClient，不连真 Milvus。

覆盖历史回归：全新环境/清库后集合不存在时，delete_by_doc 必须返回 0 而非抛异常。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _MilvusUnavailable(RuntimeError):
    """测试用哨兵：标记 MilvusClient 未配置场景。"""


@pytest.fixture
def fake_milvus_client():
    """提供可定制 has_collection/delete 的 MilvusClient 替身。"""

    def _factory(has_collection: bool, delete_return: dict | None = None, delete_side_effect=None):
        client = MagicMock()
        client.has_collection.return_value = has_collection
        if delete_side_effect is not None:
            client.delete.side_effect = delete_side_effect
        else:
            client.delete.return_value = delete_return or {"delete_count": 0}
        return client

    return _factory


def test_delete_by_doc_skips_when_collection_missing(monkeypatch, fake_milvus_client):
    """集合不存在 → 直接返回 0，不调 MilvusClient.delete（防首次入库失败）。"""
    from app.services.vectorstore import VectorStore

    client = fake_milvus_client(has_collection=False)
    monkeypatch.setattr(
        "app.services.vectorstore.MilvusClient", lambda *a, **kw: client
    )

    store = VectorStore(host="localhost", port="19530", collection="kb_chunks")
    assert store.delete_by_doc("any-doc", kb_id="default") == 0
    client.delete.assert_not_called()


def test_delete_by_doc_calls_milvus_when_collection_exists(monkeypatch, fake_milvus_client):
    """集合存在 → 构造 filter 调 MilvusClient.delete 并返回 delete_count。"""
    from app.services.vectorstore import VectorStore

    client = fake_milvus_client(has_collection=True, delete_return={"delete_count": 7})
    monkeypatch.setattr(
        "app.services.vectorstore.MilvusClient", lambda *a, **kw: client
    )

    store = VectorStore(host="localhost", port="19530", collection="kb_chunks")
    assert store.delete_by_doc("doc-xyz", kb_id="default") == 7
    client.delete.assert_called_once()
    call = client.delete.call_args
    assert call.kwargs["collection_name"] == "kb_chunks"
    assert 'doc_id == "doc-xyz"' in call.kwargs["filter"]
    assert 'kb_id == "default"' in call.kwargs["filter"]


def test_delete_by_doc_without_kb_id(monkeypatch, fake_milvus_client):
    """kb_id 为空时 filter 只含 doc_id，不叠加 kb_id 子句。"""
    from app.services.vectorstore import VectorStore

    client = fake_milvus_client(has_collection=True, delete_return={"delete_count": 1})
    monkeypatch.setattr(
        "app.services.vectorstore.MilvusClient", lambda *a, **kw: client
    )

    store = VectorStore(host="localhost", port="19530", collection="kb_chunks")
    assert store.delete_by_doc("doc-xyz", kb_id=None) == 1
    filt = client.delete.call_args.kwargs["filter"]
    assert filt == 'doc_id == "doc-xyz"'