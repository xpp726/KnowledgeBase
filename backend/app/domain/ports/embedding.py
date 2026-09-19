"""文本向量化端口与结果 DTO。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class EmbeddingError(RuntimeError):
    """Embedding 服务调用失败。"""


@dataclass
class EmbeddingResult:
    """一批文本的向量化结果，下标与输入文本一一对应。"""

    dense: list[list[float]] = field(default_factory=list)
    sparse: list[dict[int, float]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dense)


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...

    async def embed_query(self, text: str) -> tuple[list[float], dict[int, float]]: ...
