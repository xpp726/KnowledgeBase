"""BGE-M3 Embedding 客户端。

对接本机 Docker 自建的 kb-bge-m3 服务（POST /embed），
一次性取回 dense（1024 维）与 sparse（词权重）两路向量，供 Milvus 混合检索使用。

实测数据（2026-09-05，本机 RTX 3060 Laptop 6GB）：
- **首次调用 40.3 秒**：模型懒加载 + CUDA 初始化。这是正常现象，不是故障，
  `/health` 在加载完成前会返回 `model_loaded: false`。
- **热态调用 0.285 秒**
- dense 1024 维；sparse 为 `{token_id: weight}`，中等长度中文约 18 个非零项
- 单批上限 **256 条**，超出服务返回 400，故必须分批
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingError(RuntimeError):
    """Embedding 服务调用失败。"""


@dataclass
class EmbeddingResult:
    """一批文本的向量化结果，下标与输入 texts 一一对应。"""

    dense: list[list[float]] = field(default_factory=list)
    sparse: list[dict[int, float]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dense)


class EmbeddingClient:
    """BGE-M3 客户端。dense 与 sparse 一次请求同时取回，避免重复计算。"""

    def __init__(
        self,
        base_url: str | None = None,
        max_batch: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.embed_base_url).rstrip("/")
        self.max_batch = max_batch or settings.embed_max_batch
        self.timeout = timeout or settings.embed_timeout

    async def _call(self, texts: list[str]) -> tuple[list, list]:
        """调用 /embed 单批接口。返回原始 (dense_vectors, sparse_vectors)。"""
        payload = {
            "texts": texts,
            "return_dense": True,
            "return_sparse": True,
            "batch_size": min(len(texts), self.max_batch),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/embed", json=payload)
            if resp.status_code != 200:
                raise EmbeddingError(
                    f"Embedding 服务返回 {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()

        dense = data.get("dense_vectors")
        sparse = data.get("sparse_vectors")
        if not dense:
            raise EmbeddingError(
                f"响应缺少 dense_vectors，实际字段: {list(data.keys())}"
            )
        if len(dense) != len(texts):
            raise EmbeddingError(
                f"返回条数不匹配：请求 {len(texts)} 条，返回 {len(dense)} 条"
            )
        return dense, sparse or []

    @staticmethod
    def _normalize_sparse(raw: dict) -> dict[int, float]:
        """把服务的 sparse 结果规范成 Milvus 要求的 {int token_id: float weight}。

        服务返回的 key 是字符串（JSON 对象键只能是字符串），
        而 Milvus 的 SPARSE_FLOAT_VECTOR 要求 int 键，必须转换。
        """
        out: dict[int, float] = {}
        for k, v in (raw or {}).items():
            try:
                out[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """批量向量化，自动按 max_batch 切分。

        空串会被替换成占位空格：BGE-M3 对空串可能返回全零向量，
        占位后至少能拿到一个有意义的向量，避免污染索引。
        """
        if not texts:
            return EmbeddingResult()

        cleaned = [t if t and t.strip() else " " for t in texts]
        result = EmbeddingResult()

        for start in range(0, len(cleaned), self.max_batch):
            batch = cleaned[start : start + self.max_batch]
            logger.debug(
                "向量化批次 %d-%d / 共 %d 条",
                start,
                start + len(batch),
                len(cleaned),
            )
            dense, sparse = await self._call(batch)
            result.dense.extend(dense)
            result.sparse.extend(self._normalize_sparse(s) for s in sparse)

        # 极端情况下服务没返回 sparse，补空字典保持下标对齐
        while len(result.sparse) < len(result.dense):
            result.sparse.append({})

        return result

    async def embed_query(self, text: str) -> tuple[list[float], dict[int, float]]:
        """单条查询向量化，返回 (dense, sparse)。"""
        res = await self.embed([text])
        return res.dense[0], res.sparse[0]

    async def warmup(self) -> float:
        """预热：触发模型懒加载，避免首次真实请求卡 40 秒。

        建议在服务启动或入库前调用一次。返回耗时（秒）。
        """
        import time

        logger.info("正在预热 BGE-M3（首次加载约需 40 秒）...")
        t0 = time.perf_counter()
        await self.embed(["预热"])
        elapsed = time.perf_counter() - t0
        logger.info("BGE-M3 预热完成，耗时 %.1f 秒", elapsed)
        return elapsed


_client: EmbeddingClient | None = None


def get_embedder() -> EmbeddingClient:
    """进程内共享一个客户端实例。"""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
