"""应用启动与生产依赖装配。"""

from .container import (
    chunk_parsed_document,
    create_embedder,
    create_llm,
    create_storage,
    create_uow,
    create_vector_store,
    parse_document,
)

__all__ = [
    "chunk_parsed_document",
    "create_embedder",
    "create_llm",
    "create_storage",
    "create_uow",
    "create_vector_store",
    "parse_document",
]
