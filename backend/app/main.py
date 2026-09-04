"""FastAPI 入口。

提供 /api/health 用于一次性验证三个内网依赖服务（LLM / Embedding / Milvus）的连通性，
这是阶段 0 环境确认的主要手段。
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.llm import LLMProvider, get_llm

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _probe_llm(provider: LLMProvider) -> dict:
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
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _check_llm() -> dict:
    """探测当前 provider 的 LLM，以及 DeepSeek（若已配置 key）。"""
    result = {"provider": settings.llm_provider}
    result["current"] = await _probe_llm(get_llm())
    # 若配了 DeepSeek 公网 key 且当前不是 deepseek，顺带探测其连通性
    if settings.llm_provider != "deepseek" and settings.deepseek_api_key:
        result["deepseek"] = await _probe_llm(
            LLMProvider(
                name="deepseek",
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                timeout=settings.llm_timeout,
            )
        )
    return result


def _check_embedding() -> dict:
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


def _check_milvus() -> dict:
    """探测 Milvus：连通性、版本、集合是否存在。不写入任何数据。"""
    t0 = time.perf_counter()
    try:
        from pymilvus import connections, utility

        connections.connect(
            alias="healthcheck",
            host=settings.milvus_host,
            port=settings.milvus_port,
            user=settings.milvus_user or None,
            password=settings.milvus_password or None,
            timeout=20.0,
        )
        try:
            version = utility.get_server_version(using="healthcheck")
            collections = utility.list_collections(using="healthcheck")
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
            connections.disconnect("healthcheck")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health():
    """一次性验证全部依赖服务（LLM / Embedding / Milvus）。"""
    return {
        "llm": await _check_llm(),
        "embedding": _check_embedding(),
        "milvus": _check_milvus(),
        "config": {
            "llm_provider": settings.llm_provider,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "top_k": settings.milvus_top_k,
            "rerank_top_n": settings.rerank_top_n,
        },
    }
