"""健康检查 service：探测 LLM / Embedding / Milvus 连通性。

供 api/health.py 调用。本模块只做探测与结果组装，不含任何 HTTP 协议细节
（FastAPI 对象不出现在 services 层）。
"""

from __future__ import annotations

import time

import httpx

from app.config import get_settings
from app.services.llm import LLMProvider, get_llm

settings = get_settings()


async def probe_llm(provider: LLMProvider) -> dict:
    """探测单个 LLM 端点。限制 token 避免验证耗时过长。"""
    t0 = time.perf_counter()
    try:
        reply = await provider.chat(
            [{"role": "user", "content": "回复OK"}], max_tokens=8
        )
        return {
            "ok": True,
            "model": provider.model,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "reply": reply[:40],
        }
    except Exception as e:  # noqa: BLE001 健康检查需吞掉异常返回结构化结果
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def check_llm() -> dict:
    """探测当前 provider 的 LLM，以及 DeepSeek（若已配置 key）。"""
    result: dict = {"provider": settings.llm_provider}
    result["current"] = await probe_llm(get_llm())
    # 若配了 DeepSeek 公网 key 且当前不是 deepseek，顺带探测其连通性
    if settings.llm_provider != "deepseek" and settings.deepseek_api_key:
        result["deepseek"] = await probe_llm(
            LLMProvider(
                name="deepseek",
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                timeout=settings.llm_timeout,
            )
        )
    return result


def check_embedding() -> dict:
    """探测 Embedding 服务，同时确认 dense 与 sparse 是否正常返回。"""
    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"{settings.embed_base_url}/embed",
            json={
                "texts": ["连通性验证"],
                "return_dense": True,
                "return_sparse": True,
            },
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        dense = data.get("dense_vectors") or []
        sparse = data.get("sparse_vectors") or []
        return {
            "ok": True,
            "model": settings.embed_model,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "dense_dim": len(dense[0]) if dense else 0,
            "sparse_nonzero": len(sparse[0]) if sparse else 0,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def check_milvus() -> dict:
    """探测 Milvus：连通性、版本、集合是否存在。不写入任何数据。

    使用 pymilvus ≥2.4 推荐的 MilvusClient（替代 ORM-style connections/utility），
    避免 PyMilvusDeprecationWarning（旧 API 在 3.1 中移除）。
    """
    t0 = time.perf_counter()
    try:
        from pymilvus import MilvusClient

        # MilvusClient.uri 是 gRPC 端点（http://host:port），与旧 connections.connect(host=, port=) 等价
        client = MilvusClient(
            uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
            user=settings.milvus_user or "",
            password=settings.milvus_password or "",
            timeout=20.0,
        )
        try:
            version = client.get_server_version()
            collections = client.list_collections()
            target_exists = settings.milvus_collection in collections
            return {
                "ok": True,
                "version": version,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "collections": collections,
                "target_collection": settings.milvus_collection,
                "target_exists": target_exists,
            }
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def check_mysql() -> dict:
    """探测业务数据库（MySQL/SQLite）：连通性 + 方言 + 版本。不写任何数据。"""
    t0 = time.perf_counter()
    try:
        from sqlalchemy import text

        from app.db import async_engine

        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            dialect = async_engine.dialect.name
            if dialect == "mysql":
                version = (await conn.execute(text("SELECT VERSION()"))).scalar()
            elif dialect == "sqlite":
                version = (await conn.execute(text("SELECT sqlite_version()"))).scalar()
            else:
                version = None
        return {
            "ok": True,
            "dialect": dialect,
            "version": version,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def check_minio() -> dict:
    """探测 MinIO：连通性、bucket 列表、目标 bucket 是否存在。不写入。"""
    t0 = time.perf_counter()
    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        buckets = [b.name for b in client.list_buckets()]
        bucket_exists = settings.minio_bucket in buckets
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "buckets": buckets,
            "target_bucket": settings.minio_bucket,
            "target_exists": bucket_exists,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def full_health() -> dict:
    """聚合五项探测与关键配置，供健康端点直接返回。"""
    return {
        "llm": await check_llm(),
        "embedding": check_embedding(),
        "milvus": check_milvus(),
        "mysql": await check_mysql(),
        "minio": check_minio(),
        "config": {
            "llm_provider": settings.llm_provider,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "top_k": settings.milvus_top_k,
            "rerank_top_n": settings.rerank_top_n,
        },
    }
