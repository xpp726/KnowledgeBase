"""向量检索端口与检索结果 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class VectorStoreError(RuntimeError):
    """向量库操作失败。"""


@dataclass
class Hit:
    """检索命中结果。"""

    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int
    score: float
    kb_id: str = "default"

    def __repr__(self) -> str:
        return f"<Hit {self.chunk_id} score={self.score:.4f} {self.doc_name[:30]}>"


class VectorStore(Protocol):
    """文档入库与检索所需的向量库能力。"""

    def ensure_collection(self, drop_if_exists: bool = False) -> None: ...

    def insert(self, rows: list[dict[str, Any]], batch_size: int = 200) -> int: ...

    def delete_by_doc(self, doc_id: str, kb_id: str | None = None) -> int: ...

    def hybrid_search(
        self,
        dense: list[float],
        sparse: dict[int, float],
        top_k: int | None = None,
        kb_id: str | None = None,
    ) -> list[Hit]: ...

    def dense_search(
        self,
        dense: list[float],
        top_k: int | None = None,
        kb_id: str | None = None,
    ) -> list[Hit]: ...

    def sparse_search(
        self,
        sparse: dict[int, float],
        top_k: int | None = None,
        kb_id: str | None = None,
    ) -> list[Hit]: ...
