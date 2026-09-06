"""测试替身（Fake）：离线替代 Embedding / VectorStore / LLM，不触达任何外部服务。"""

from __future__ import annotations

from app.services.embedding import EmbeddingResult
from app.services.vectorstore import Hit


def make_hit(
    chunk_id: str = "c1",
    *,
    doc_id: str = "d1",
    doc_name: str = "doc.pdf",
    text: str = "一段命中的正文内容",
    page: int = 1,
    score: float = 0.8,
    kb_id: str = "default",
) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_name=doc_name,
        text=text,
        page=page,
        score=score,
        kb_id=kb_id,
    )


class FakeEmbedder:
    """返回固定维度向量；记录最后一次 query。"""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.last_query: str | None = None

    async def embed_query(self, text: str):
        self.last_query = text
        return [0.1] * self.dim, {1: 0.5}

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            dense=[[0.1] * self.dim for _ in texts],
            sparse=[{1: 0.5} for _ in texts],
        )


class FakeVectorStore:
    """按预设 hits 返回；记录被调用的检索路线与参数，供断言。"""

    def __init__(self, hits: list[Hit] | None = None):
        self.hits = hits or []
        self.calls: list[tuple] = []
        self.deleted: list[tuple] = []

    def dense_search(self, dense, top_k=None, kb_id=None) -> list[Hit]:
        self.calls.append(("dense", top_k, kb_id))
        return self.hits

    def hybrid_search(self, dense, sparse, top_k=None, kb_id=None) -> list[Hit]:
        self.calls.append(("hybrid", top_k, kb_id))
        return self.hits

    def sparse_search(self, sparse, top_k=None, kb_id=None) -> list[Hit]:
        self.calls.append(("sparse", top_k, kb_id))
        return self.hits

    def delete_by_doc(self, doc_id: str, kb_id: str = "default") -> int:
        self.deleted.append((doc_id, kb_id))
        return len(self.hits)


class FakeStorage:
    """内存文件存储（put/get/delete/exists/list_keys 全量实现），离线可重复。"""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.files[key] = data

    def get(self, key: str) -> bytes:
        if key not in self.files:
            from app.services.storage import ObjectNotFoundError

            raise ObjectNotFoundError(key)
        return self.files[key]

    def delete(self, key: str) -> None:
        self.files.pop(key, None)
        self.deleted_keys.append(key)

    def exists(self, key: str) -> bool:
        return key in self.files

    def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in self.files if k.startswith(prefix)]


class FakeLLM:
    """chat_stream 按预设片段逐段产出；可配置抛错；记录是否被调用。"""

    def __init__(self, pieces=("这是答案",), raise_exc: Exception | None = None):
        self.pieces = list(pieces)
        self.raise_exc = raise_exc
        self.stream_calls = 0
        self.last_messages: list[dict] | None = None

    async def chat_stream(self, messages, *, max_tokens=None, temperature=None):
        self.stream_calls += 1
        self.last_messages = messages
        if self.raise_exc is not None:
            raise self.raise_exc
        for piece in self.pieces:
            yield piece

    async def chat(self, messages, *, max_tokens=None, temperature=None) -> str:
        return "".join(self.pieces)


async def collect_events(agen) -> list[dict]:
    """把 async generator 的事件收集成 list。"""
    out: list[dict] = []
    async for ev in agen:
        out.append(ev)
    return out
