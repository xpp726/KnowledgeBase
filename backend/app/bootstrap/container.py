"""生产依赖装配入口。

Application 层只依赖 Domain Port 和可替换的工厂；具体的数据库、存储、向量库、
Embedding、LLM 以及解析器实现都在这里集中装配。外部实现采用延迟导入，避免
应用业务模块在导入期建立外部客户端或加载重量级 SDK。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.application.runtime import configure_runtime
from app.domain.ports.embedding import Embedder
from app.domain.ports.file_storage import FileStorage
from app.domain.ports.llm import LLMClient
from app.domain.ports.vector_store import VectorStore
from app.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def create_uow(*, auto_commit: bool = False) -> SqlAlchemyUnitOfWork:
    """创建一个数据库 Unit of Work。生命周期由调用方管理。"""
    return SqlAlchemyUnitOfWork(auto_commit=auto_commit)


def create_storage() -> FileStorage:
    """创建当前配置对应的文件存储实现。"""
    from app.infrastructure.storage.provider import get_storage

    return get_storage()


def create_vector_store() -> VectorStore:
    """创建当前配置对应的向量库实现。"""
    from app.infrastructure.vectorstore.milvus import get_vectorstore

    return get_vectorstore()


def create_embedder() -> Embedder:
    """创建当前配置对应的文本向量化实现。"""
    from app.infrastructure.embedding.bge_m3 import get_embedder

    return get_embedder()


def create_llm() -> LLMClient:
    """创建当前配置对应的大语言模型实现。"""
    from app.infrastructure.llm.openai_compatible import get_llm

    return get_llm()


def parse_document(path: Path, doc_id: str) -> Any:
    """调用当前配置的文档解析器。

    解析器属于 Infrastructure，Application 只接收解析结果，不直接依赖具体
    parser 模块。保留同步调用约定，由调用方决定是否放入线程池。
    """
    from app.infrastructure.parsing.parsers import parse_file

    return parse_file(path, doc_id)


def chunk_parsed_document(parsed: Any) -> list[Any]:
    """调用当前配置的文档分块器。"""
    from app.infrastructure.parsing.chunker import chunk_document

    return chunk_document(parsed)


# 注册只在组合根发生，Application 模块本身不反向导入本文件。
configure_runtime(
    uow_factory=create_uow,
    storage_factory=create_storage,
    vector_store_factory=create_vector_store,
    embedder_factory=create_embedder,
    llm_factory=create_llm,
    parser=parse_document,
    chunker=chunk_parsed_document,
)
