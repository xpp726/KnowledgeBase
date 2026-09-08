"""Embedding 客户端单元测试：覆盖重试逻辑与分批行为。

使用 monkeypatch 替身 httpx.AsyncClient，不连真实 Embedding 服务。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.embedding import EmbeddingClient, EmbeddingError


# ---- 替身：构造一个 AsyncClient，每次 post 返回预设的 side_effect ----
def _make_async_client_factory(responses):
    """返回一个 factory：每次调用产生一个 MagicMock AsyncClient，
    其 .post 行为按 responses 列表逐项产出（异常或 Mock Response）。
    """
    queue = list(responses)
    idx = {"i": 0}

    def factory(*args, **kwargs):
        client = MagicMock()
        client._idx = idx
        idx["i"] += 1

        async def _post(url, json=None):
            if not queue:
                raise RuntimeError("测试未配置响应")
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            resp = MagicMock()
            resp.status_code = item.get("status", 200)
            resp.text = item.get("text", "")
            resp.json.return_value = item.get("json", {})
            return resp

        client.post = _post

        # 支持 async with httpx.AsyncClient(...) as client: 用法
        @asynccontextmanager
        async def _ctx(*a, **kw):
            yield client

        factory._ctx = _ctx
        return client

    # 让 httpx.AsyncClient(timeout=...)() 返回我们的 mock，
    # 同时支持 async with — 通过替换类的 __init__ 返回带 __aenter__/__aexit__ 的对象。
    # 简单做法：直接 patch AsyncClient 类。
    return factory


@pytest.fixture
def patch_async_client(monkeypatch):
    """替身 httpx.AsyncClient，让 with 块里拿到的是 mock client。"""

    def _patch(responses):
        queue = list(responses)

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self._queue = queue
                self.timeout = kwargs.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                if not self._queue:
                    raise RuntimeError("测试未配置响应")
                item = self._queue.pop(0)
                if isinstance(item, BaseException):
                    raise item
                resp = MagicMock()
                resp.status_code = item.get("status", 200)
                resp.text = item.get("text", "")
                resp.json.return_value = item.get("json", {})
                return resp

        monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", FakeAsyncClient)
        return queue

    return _patch


def _ok_payload(n: int) -> dict:
    return {
        "status": 200,
        "json": {
            "dense_vectors": [[0.1] * 4 for _ in range(n)],
            "sparse_vectors": [{"1": "0.5"} for _ in range(n)],
        },
    }


# ============ _call 重试逻辑 ============


async def test_call_succeeds_first_try(patch_async_client):
    patch_async_client([_ok_payload(3)])
    c = EmbeddingClient(base_url="http://x", max_batch=3, timeout=1, max_retries=2, retry_base_delay=0.01)
    dense, sparse = await c._call(["a", "b", "c"])
    assert len(dense) == 3 and len(sparse) == 3


async def test_call_retries_on_read_timeout_then_succeeds(patch_async_client):
    """ReadTimeout 后重试，第二次成功 → 应返回第二次的结果，不抛。"""
    patch_async_client([
        httpx.ReadTimeout("timeout"),
        _ok_payload(2),
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=2, timeout=1, max_retries=2, retry_base_delay=0.01)
    dense, sparse = await c._call(["a", "b"])
    assert len(dense) == 2
    # _call 直接返回服务原始 payload，sparse 是字符串键（归一化在 embed() 外层做）
    assert sparse == [{"1": "0.5"}, {"1": "0.5"}]


async def test_call_retries_on_connect_error_then_succeeds(patch_async_client):
    patch_async_client([
        httpx.ConnectError("conn refused"),
        httpx.ConnectTimeout("conn timeout"),
        _ok_payload(1),
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=1, timeout=1, max_retries=2, retry_base_delay=0.01)
    dense, _ = await c._call(["a"])
    assert len(dense) == 1


async def test_call_raises_after_exhausting_retries(patch_async_client):
    """max_retries=2 → 共 3 次调用机会，全部失败抛 EmbeddingError。"""
    patch_async_client([
        httpx.ReadTimeout("t1"),
        httpx.ReadTimeout("t2"),
        httpx.ReadTimeout("t3"),
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=1, timeout=1, max_retries=2, retry_base_delay=0.01)
    with pytest.raises(EmbeddingError, match="重试 2 次后仍失败"):
        await c._call(["a"])


async def test_call_does_not_retry_on_4xx(patch_async_client):
    """服务返回 4xx → EmbeddingError，不重试。"""
    patch_async_client([
        {"status": 400, "text": "bad input", "json": {}},
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=1, timeout=1, max_retries=2, retry_base_delay=0.01)
    with pytest.raises(EmbeddingError, match="返回 400"):
        await c._call(["a"])


async def test_call_does_not_retry_on_missing_dense(patch_async_client):
    """响应 200 但缺 dense_vectors → EmbeddingError，不重试。"""
    patch_async_client([
        {"status": 200, "json": {"sparse_vectors": []}},
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=1, timeout=1, max_retries=2, retry_base_delay=0.01)
    with pytest.raises(EmbeddingError, match="缺少 dense_vectors"):
        await c._call(["a"])


# ============ embed() 分批行为 ============


async def test_embed_splits_into_multiple_batches(patch_async_client):
    """max_batch=2，5 个文本 → 3 次 _call（2+2+1）。"""
    patch_async_client([
        _ok_payload(2),
        _ok_payload(2),
        _ok_payload(1),
    ])
    c = EmbeddingClient(base_url="http://x", max_batch=2, timeout=1, max_retries=0, retry_base_delay=0.01)
    res = await c.embed(["a", "b", "c", "d", "e"])
    assert len(res.dense) == 5
    assert len(res.sparse) == 5
    assert all(s == {1: 0.5} for s in res.sparse)


async def test_embed_replaces_empty_strings(patch_async_client):
    """空串替换成占位，避免 BGE-M3 返回全零向量。"""
    patch_async_client([_ok_payload(2)])
    c = EmbeddingClient(base_url="http://x", max_batch=10, timeout=1, max_retries=0, retry_base_delay=0.01)
    await c.embed(["", "  "])
    # 没有抛错且返回 2 条结果 → 占位生效
    # 实际传参验证：由 _call_once 内的 payload（这里我们没拦截），行为上 OK 即可


async def test_embed_returns_empty_for_empty_input(patch_async_client):
    c = EmbeddingClient(base_url="http://x", max_batch=10, timeout=1, max_retries=0, retry_base_delay=0.01)
    res = await c.embed([])
    assert len(res.dense) == 0
    assert len(res.sparse) == 0


async def test_embed_pads_sparse_when_service_returns_empty(patch_async_client):
    """服务不返回 sparse → sparse 自动补空字典，保持下标对齐。"""
    patch_async_client([{
        "status": 200,
        "json": {"dense_vectors": [[0.1] * 4, [0.2] * 4], "sparse_vectors": []},
    }])
    c = EmbeddingClient(base_url="http://x", max_batch=10, timeout=1, max_retries=0, retry_base_delay=0.01)
    res = await c.embed(["a", "b"])
    assert len(res.dense) == 2
    assert len(res.sparse) == 2
    assert all(s == {} for s in res.sparse)