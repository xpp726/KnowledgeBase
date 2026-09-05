"""文档管理 service：登记 / 处理 / 重试 / 删除补偿 / 卡死恢复 / 查询。

分层：本模块做业务编排，状态合法性走 ``doc_states``，ORM 读写走 ``models.queries``，
解析-分块-向量化流水线复用 ``services.ingestion``，不重复实现。

删除补偿（方案 §4 定序，跨三个异构系统无法做分布式事务，用"定序 + 记账本 + 可重入"）：
    ① Milvus 向量（检索立刻不可见，删除幂等）
    ② 对象存储原始文件（delete 对不存在的 key 静默，幂等）
    ③ DB 记录（**最后删**：它是记录向量 id / 文件 key 的账本，前两步任一中途失败，
       账本仍在，可安全重跑本函数，已成功的步骤幂等跳过）
每步成功才进下一步；失败写日志并带着已完成情况返回，供 scripts/cleanup.py 兜底重跑。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.db import get_async_session
from app.models import queries
from app.services import doc_states
from app.services.embedding import get_embedder
from app.services.ingestion import (
    IngestResult,
    ingest_bytes,
    make_doc_id,
    storage_key,
)
from app.services.storage import FileStorage, get_storage
from app.services.vectorstore import VectorStore, get_vectorstore

logger = logging.getLogger(__name__)
settings = get_settings()


class DocumentNotFoundError(RuntimeError):
    """文档不存在。"""


# ==================== 结果对象 ====================

@dataclass
class DeleteReport:
    """一次删除补偿的逐步结果，可序列化返回给调用方 / 写入日志。"""

    doc_id: str
    found: bool = True
    vector_deleted: int = 0
    file_deleted: bool = False
    db_deleted: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """账本不存在视为幂等成功；存在则要求无错且 DB 已删。"""
        return self.found and not self.errors and self.db_deleted or not self.found

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "found": self.found,
            "vector_deleted": self.vector_deleted,
            "file_deleted": self.file_deleted,
            "db_deleted": self.db_deleted,
            "ok": self.ok,
            "errors": self.errors,
        }


def _doc_dict(doc) -> dict:
    return {
        "doc_id": doc.doc_id,
        "kb_id": doc.kb_id,
        "file_name": doc.file_name,
        "file_path": doc.file_path,
        "file_ext": doc.file_ext,
        "file_size": doc.file_size,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "table_chunks": doc.table_chunks,
        "status": doc.status,
        "error": doc.error,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


# ==================== 登记 / 处理 / 重试 ====================

async def register_document(
    data: bytes,
    file_name: str,
    *,
    kb_id: str | None = None,
    storage: FileStorage | None = None,
) -> dict:
    """上传第一步：原始文件落存储 + 文档登记为 pending（尚未解析）。

    已处于处理中的同名文档幂等返回，避免并发重复入库；done/failed 则重新登记回 pending。
    """
    kb_id = kb_id or settings.default_kb_id
    doc_id = make_doc_id(file_name)
    storage = storage or get_storage()
    key = storage_key(kb_id, doc_id, file_name)
    await asyncio.to_thread(storage.put, key, data)

    async with get_async_session() as session:
        await queries.ensure_knowledge_base(
            session,
            kb_id,
            name=settings.default_kb_name if kb_id == settings.default_kb_id else kb_id,
        )
        doc = await queries.get_document(session, doc_id)
        if doc is not None:
            if doc.status in doc_states.IN_PROGRESS:
                logger.info("文档 %s 正处于 %s，登记幂等返回", file_name, doc.status)
                return _doc_dict(doc)
            doc_states.assert_transition(doc.status, doc_states.PENDING)
        return _doc_dict(
            await queries.upsert_document(
                session,
                doc_id=doc_id,
                status=doc_states.PENDING,
                kb_id=kb_id,
                file_name=file_name,
                file_path=key,
                file_ext="." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "",
                file_size=len(data),
                error="",
            )
        )


async def process_bytes(
    data: bytes,
    file_name: str,
    *,
    kb_id: str | None = None,
    force: bool = False,
    embedder=None,
    store: VectorStore | None = None,
    storage: FileStorage | None = None,
) -> IngestResult:
    """处理文档字节（解析→分块→向量化→入库），状态机由 ingestion 内部逐段校验。"""
    return await ingest_bytes(
        data,
        file_name,
        kb_id=kb_id,
        embedder=embedder or get_embedder(),
        store=store or get_vectorstore(),
        storage=storage or get_storage(),
        force=force,
    )


async def reprocess(
    doc_id: str,
    *,
    embedder=None,
    store: VectorStore | None = None,
    storage: FileStorage | None = None,
) -> IngestResult:
    """重试：从对象存储读回原始文件，force 重跑流水线（failed/done → ingesting）。"""
    storage = storage or get_storage()
    async with get_async_session() as session:
        doc = await queries.get_document(session, doc_id)
        if doc is None:
            raise DocumentNotFoundError(doc_id)
        file_name, file_path, kb_id = doc.file_name, doc.file_path, doc.kb_id

    if not file_path:
        raise DocumentNotFoundError(f"{doc_id} 缺少原始文件路径，无法重试")
    data = await asyncio.to_thread(storage.get, file_path)
    return await process_bytes(
        data,
        file_name,
        kb_id=kb_id,
        force=True,
        embedder=embedder,
        store=store,
        storage=storage,
    )


# ==================== 删除补偿 ====================

async def delete_document(
    doc_id: str,
    *,
    kb_id: str | None = None,
    store: VectorStore | None = None,
    storage: FileStorage | None = None,
) -> DeleteReport:
    """按 ①向量 → ②文件 → ③DB 的顺序删除，任一步失败即带账本返回，可安全重跑。"""
    store = store or get_vectorstore()
    storage = storage or get_storage()
    report = DeleteReport(doc_id=doc_id)

    async with get_async_session() as session:
        doc = await queries.get_document(session, doc_id)
        if doc is None:
            # 账本已不存在：视为幂等成功（可能上次已删完），不再尝试外部资源
            report.found = False
            logger.info("删除补偿：文档 %s 账本不存在，幂等返回", doc_id)
            return report
        eff_kb = kb_id or doc.kb_id
        key = doc.file_path

    # ① Milvus 向量（幂等：重复删返回 0）
    try:
        report.vector_deleted = int(
            await asyncio.to_thread(store.delete_by_doc, doc_id, eff_kb)
        )
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"vector: {type(e).__name__}: {e}")
        logger.error("删除向量失败 %s（账本保留，可重跑）: %s", doc_id, e)
        return report

    # ② 对象存储原始文件（幂等：删不存在的 key 静默）
    if key:
        try:
            await asyncio.to_thread(storage.delete, key)
            report.file_deleted = True
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"file: {type(e).__name__}: {e}")
            logger.error("删除文件失败 %s（向量已删，账本保留，可重跑）: %s", doc_id, e)
            return report

    # ③ DB 记录最后删（账本）
    try:
        async with get_async_session() as session:
            await queries.delete_document_rows(session, doc_id)
        report.db_deleted = True
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"db: {type(e).__name__}: {e}")
        logger.error("删除 DB 记录失败 %s（外部资源已清，可重跑清账本）: %s", doc_id, e)
        return report

    logger.info(
        "删除补偿完成 %s：向量 %d 条、文件 %s、DB 已删",
        doc_id, report.vector_deleted, report.file_deleted,
    )
    return report


# ==================== 卡死恢复 ====================

async def recover_stuck(timeout_seconds: int | None = None) -> list[str]:
    """把停在处理态超过阈值的文档标记 failed（单进程崩溃后的启动恢复）。"""
    timeout = timeout_seconds or settings.stuck_timeout_seconds
    before = time.time() - timeout
    recovered: list[str] = []
    async with get_async_session() as session:
        stuck = await queries.list_stuck_documents(session, set(doc_states.IN_PROGRESS), before)
        for doc in stuck:
            old = doc.status
            doc_states.assert_transition(old, doc_states.FAILED)
            doc.status = doc_states.FAILED
            doc.error = f"进程中断：{old} 状态超过 {timeout}s 未推进，启动时判定卡死，可重试"
            recovered.append(doc.doc_id)
            logger.warning("卡死恢复：%s %s → failed", doc.doc_id, old)
    if recovered:
        logger.info("共恢复 %d 个卡死文档：%s", len(recovered), recovered)
    return recovered


# ==================== 查询 ====================

async def get_document(doc_id: str) -> dict | None:
    async with get_async_session() as session:
        doc = await queries.get_document(session, doc_id)
        return _doc_dict(doc) if doc else None


async def list_documents(
    kb_id: str | None = None, status: str | None = None
) -> list[dict]:
    async with get_async_session() as session:
        rows = await queries.list_documents(session, kb_id=kb_id, status=status)
        return [_doc_dict(d) for d in rows]
