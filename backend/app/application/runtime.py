"""Application 层的外部能力注册表。

本模块只保存可替换的工厂协议，不导入任何 Infrastructure 实现。
生产组合根由 ``app.bootstrap.container`` 注册真实实现；测试可以直接注册
Fake，或继续替换各 Application 模块暴露的工厂名称。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


class _Runtime:
    uow_factory: Callable[..., Any] | None = None
    storage_factory: Callable[[], Any] | None = None
    vector_store_factory: Callable[[], Any] | None = None
    embedder_factory: Callable[[], Any] | None = None
    llm_factory: Callable[[], Any] | None = None
    parser: Callable[[Path, str], Any] | None = None
    chunker: Callable[[Any], list[Any]] | None = None


_runtime = _Runtime()


def configure_runtime(
    *,
    uow_factory: Callable[..., Any],
    storage_factory: Callable[[], Any],
    vector_store_factory: Callable[[], Any],
    embedder_factory: Callable[[], Any],
    llm_factory: Callable[[], Any],
    parser: Callable[[Path, str], Any],
    chunker: Callable[[Any], list[Any]],
) -> None:
    """由组合根一次性注册 Application 所需的外部能力。"""
    _runtime.uow_factory = uow_factory
    _runtime.storage_factory = storage_factory
    _runtime.vector_store_factory = vector_store_factory
    _runtime.embedder_factory = embedder_factory
    _runtime.llm_factory = llm_factory
    _runtime.parser = parser
    _runtime.chunker = chunker


def _required(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(
            f"Application runtime 未配置 {name}，请先导入并初始化 app.bootstrap.container"
        )
    return value


def create_uow(*, auto_commit: bool = False) -> Any:
    factory = _required("uow_factory", _runtime.uow_factory)
    return factory(auto_commit=auto_commit)


def create_storage() -> Any:
    return _required("storage_factory", _runtime.storage_factory)()


def create_vector_store() -> Any:
    return _required("vector_store_factory", _runtime.vector_store_factory)()


def create_embedder() -> Any:
    return _required("embedder_factory", _runtime.embedder_factory)()


def create_llm() -> Any:
    return _required("llm_factory", _runtime.llm_factory)()


def parse_document(path: Path, doc_id: str) -> Any:
    return _required("parser", _runtime.parser)(path, doc_id)


def chunk_parsed_document(parsed: Any) -> list[Any]:
    return _required("chunker", _runtime.chunker)(parsed)
