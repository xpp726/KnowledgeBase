"""BGE-M3 向量化服务：同时输出 dense 与 sparse 向量。

接口与内网 docmind-embed (8003) 完全对齐，可无痛热切换。
sparse 向量是 BGE-M3 的词权重输出，用于混合检索的关键词分支。
"""

from __future__ import annotations

import os
import time
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("MODEL_NAME", "BAAI/bge-m3")
MAX_TEXTS = int(os.getenv("MAX_TEXTS", "256"))
DEFAULT_BATCH = int(os.getenv("DEFAULT_BATCH", "32"))
USE_FP16 = os.getenv("USE_FP16", "true").lower() == "true"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

app = FastAPI(title="bge-m3-embed", version="1.0.0")

_model = None
_load_error: str | None = None


def get_model():
    """懒加载模型，首次请求时才载入显存。"""
    global _model, _load_error
    if _model is not None:
        return _model
    if _load_error:
        raise RuntimeError(_load_error)
    try:
        from FlagEmbedding import BGEM3FlagModel

        _model = BGEM3FlagModel(
            MODEL_NAME,
            use_fp16=(USE_FP16 and DEVICE == "cuda"),
            devices=None,
        )
        return _model
    except Exception as e:  # noqa: BLE001
        _load_error = f"{type(e).__name__}: {e}"
        raise


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., description="待向量化文本列表")
    batch_size: int | None = Field(None, description="内部分批大小")
    return_dense: bool | None = Field(True, description="是否返回稠密向量")
    return_sparse: bool | None = Field(True, description="是否返回稀疏向量")


class EmbedResponse(BaseModel):
    dense_vectors: list[list[float]] | None = None
    sparse_vectors: list[dict[int, float]] | None = None
    message: str = "success"


def _run(texts: list[str], want_dense: bool, want_sparse: bool, batch_size: int):
    model = get_model()
    dense_all: list[list[float]] = []
    sparse_all: list[dict[int, float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        out = model.encode(
            batch,
            return_dense=want_dense,
            return_sparse=want_sparse,
            return_colbert_vecs=False,
        )
        if want_dense:
            dense_all.extend(out["dense_vecs"].tolist())
        if want_sparse:
            for lw in out["lexical_weights"]:
                sparse_all.append({int(k): round(float(v), 6) for k, v in lw.items()})

    return (
        dense_all if want_dense else None,
        sparse_all if want_sparse else None,
    )


@app.get("/health")
def health():
    return {
        "status": "ok" if _load_error is None else "error",
        "version": "1.0.0",
        "model_name": MODEL_NAME,
        "device": DEVICE,
        "fp16": USE_FP16 and DEVICE == "cuda",
        "model_loaded": _model is not None,
        "load_error": _load_error,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts 不能为空")
    if len(req.texts) > MAX_TEXTS:
        raise HTTPException(
            status_code=400,
            detail=f"单次请求最多 {MAX_TEXTS} 条文本，当前 {len(req.texts)} 条",
        )

    want_dense = bool(req.return_dense)
    want_sparse = bool(req.return_sparse)
    if not want_dense and not want_sparse:
        raise HTTPException(status_code=400, detail="dense 与 sparse 至少返回一个")

    bs = req.batch_size or DEFAULT_BATCH
    bs = max(1, min(bs, MAX_TEXTS))

    t0 = time.time()
    try:
        dense, sparse = _run(req.texts, want_dense, want_sparse, bs)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e

    return EmbedResponse(
        dense_vectors=dense,
        sparse_vectors=sparse,
        message=f"success ({time.time() - t0:.3f}s)",
    )


class OpenAIEmbedRequest(BaseModel):
    model: str | None = None
    input: list[str] | str = ...


@app.post("/v1/embeddings")
def openai_embed(req: OpenAIEmbedRequest):
    """OpenAI 兼容接口，仅返回 dense，便于对接标准工具链。"""
    texts = [req.input] if isinstance(req.input, str) else req.input
    if len(texts) > MAX_TEXTS:
        raise HTTPException(status_code=400, detail=f"单次最多 {MAX_TEXTS} 条")
    dense, _ = _run(texts, True, False, DEFAULT_BATCH)
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [
            {"object": "embedding", "index": i, "embedding": v}
            for i, v in enumerate(dense)
        ],
        "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": 0},
    }
