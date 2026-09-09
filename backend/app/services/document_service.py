"""文档管理 service：登记 / 处理 / 重试 / 删除补偿 / 卡死恢复 / 查询。

分层：本模块做业务编排，状态合法性走 ``doc_states``，ORM 读写走 ``models.queries``，
解析-分块-向量化流水线复用 ``services.ingestion``，不重复实现。

folder 集成：
- register_document 支持 folder_id；folder 为空时自动用默认 folder（kb 级 root）。
- 同 folder 下 file_name 重复 → 拒绝并提示（不静默覆盖）。
- list_documents_paginated 支持 folder_id 过滤；DocumentOut.folder_path 由 folder_service.get_folder_path_map 拼装。

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
from app.models.document import Document
from app.services import doc_states
from app.services import folder_service as folder_svc
from app.services.embedding import get_embedder
from app.services.ingestion import (
    IngestResult,
    ingest_bytes,
    make_doc_id,
    storage_key,
)
from app.services.storage import FileStorage, ObjectNotFoundError, get_storage
from app.services.vectorstore import VectorStore, get_vectorstore

logger = logging.getLogger(__name__)
settings = get_settings()

# 文档解析并发信号量：限制同时跑解析/向量化的文档数（embedding/Milvus 瓶颈），
# 其余排队的文档保持 pending，被调度时才推进状态机（多文件上传防打爆）
_ingest_semaphore = asyncio.Semaphore(settings.max_concurrent_ingest)


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


def _doc_dict(doc, folder_path: str = "") -> dict:
    return {
        "doc_id": doc.doc_id,
        "kb_id": doc.kb_id,
        "folder_id": doc.folder_id,
        "folder_path": folder_path,
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


def _kb_dict(kb, doc_count: int = 0) -> dict:
    return {
        "kb_id": kb.kb_id,
        "name": kb.name,
        "description": kb.description,
        "doc_count": doc_count,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
    }


# ==================== 登记 / 处理 / 重试 ====================

async def register_document(
    data: bytes,
    file_name: str,
    *,
    kb_id: str | None = None,
    folder_id: str | None = None,
    storage: FileStorage | None = None,
) -> dict:
    """上传第一步：原始文件落存储 + 文档登记为 pending（尚未解析）。

    folder 集成：
    - folder_id 为空 → 自动用该 kb 的默认 folder（kb 级 root）
    - folder 跨 kb / 同 folder 内 file_name 重复 → 抛 FolderNameConflictError
    - doc_id 按 kb_id/folder_id/file_name 三者哈希（跨 folder 同名 → 独立 doc_id）

    已处于处理中的同 folder 同名文档幂等返回；其他情况拒绝并提示。
    返回 dict 含 duplicated 标志（同 doc_id 已存在），供前端上传确认提示。
    """
    kb_id = kb_id or settings.default_kb_id
    storage = storage or get_storage()

    async with get_async_session() as session:
        # 1. 确保 kb 存在
        await queries.ensure_knowledge_base(
            session,
            kb_id,
            name=settings.default_kb_name if kb_id == settings.default_kb_id else kb_id,
        )
        # 2. folder 解析：None → 默认 folder
        if folder_id is None:
            df = await queries.ensure_default_folder(session, kb_id)
            folder_id = df.folder_id
        else:
            folder = await queries.get_folder(session, folder_id)
            if folder is None:
                raise folder_svc.FolderNotFoundError(f"folder 不存在：{folder_id}")
            if folder.kb_id != kb_id:
                raise folder_svc.FolderKbMismatchError(kb_id, folder.kb_id)

        # 3. folder 内 file_name 唯一性校验（用户决策"folder 内同名拒绝"）：
        #    任何同名记录（无论 doc_id 是否相同）都拒绝；如需重新入库，
        #    走 POST /documents/{id}/reprocess 接口（保留原有"重新解析"语义）。
        same_name = await queries.find_document_by_folder_name(
            session, kb_id, folder_id, file_name
        )
        if same_name is not None:
            raise folder_svc.FileNameConflictError(
                f"目录内已存在同名文件「{file_name}」，请重命名后重传或删除原文件后重传"
            )

        # 4. 算 doc_id（按新算法 kb/folder/file）
        doc_id = make_doc_id(kb_id, folder_id, file_name)
        # 5. 落存储（基于新 doc_id）
        key = storage_key(kb_id, doc_id, file_name)
        await asyncio.to_thread(storage.put, key, data)

        # 6. 查账本（doc_id 维度唯一）：同 doc_id 可能来自 doc_id 算法巧合碰撞，
        #    此时走 upsert 覆盖（被覆盖的文档记录在另一 folder，应是用户操作错误）
        doc = await queries.get_document(session, doc_id)
        if doc is not None:
            if doc.status in doc_states.IN_PROGRESS:
                logger.info("文档 %s 正处于 %s，登记幂等返回", file_name, doc.status)
                out = _doc_dict(
                    doc,
                    folder_path=folder_svc.build_folder_path(
                        doc.folder_id,
                        await folder_svc.get_folder_path_map(kb_id),
                    ),
                )
                out["duplicated"] = True
                return out
            doc_states.assert_transition(doc.status, doc_states.PENDING)

        # 7. 写账本（含 folder_id 字段透传）
        out = _doc_dict(
            await queries.upsert_document(
                session,
                doc_id=doc_id,
                status=doc_states.PENDING,
                kb_id=kb_id,
                folder_id=folder_id,
                file_name=file_name,
                file_path=key,
                file_ext="." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "",
                file_size=len(data),
                error="",
            )
        )
        out["duplicated"] = doc is not None
        out["folder_path"] = folder_svc.build_folder_path(
            folder_id, await folder_svc.get_folder_path_map(kb_id)
        )
        return out


async def process_bytes(
    data: bytes,
    file_name: str,
    *,
    kb_id: str | None = None,
    doc_id: str | None = None,
    folder_id: str | None = None,
    force: bool = False,
    embedder=None,
    store: VectorStore | None = None,
    storage: FileStorage | None = None,
) -> IngestResult:
    """处理文档字节（解析→分块→向量化→入库），状态机由 ingestion 内部逐段校验。

    doc_id / folder_id 透传至 ingest_bytes → make_doc_id 时优先使用传值（与 register_document 一致），
    避免 folder_id 为 None 时算出旧算法的 hash（与注册时不一致），从而把 chunks/status 写到错的 doc。
    """
    return await ingest_bytes(
        data,
        file_name,
        doc_id=doc_id,
        folder_id=folder_id,
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
        doc_id=doc_id,  # ← 透传，doc_id 一致才能把 chunks / status 写到正确的 row
        kb_id=kb_id,
        force=True,
        embedder=embedder,
        store=store,
        storage=storage,
    )


# ==================== 异步调度（上传/重试统一入口） ====================

async def _run_ingest(doc_id: str) -> None:
    """信号量限流后执行解析流水线；文档被删除等情况静默跳过。"""
    async with _ingest_semaphore:
        try:
            await reprocess(doc_id)
        except DocumentNotFoundError:
            logger.info("调度跳过：文档 %s 已不存在（可能已删除）", doc_id)
        except Exception as exc:  # noqa: BLE001 流水线内部已落 failed，这里只兜底日志
            logger.error("调度解析异常 %s: %s", doc_id, exc)


def schedule_ingest(doc_id: str) -> None:
    """登记/重试后调度异步解析，不阻塞请求；排队由信号量控制。"""
    asyncio.create_task(_run_ingest(doc_id))


# ==================== 移动（folder 归属变更） ====================

async def move_documents(doc_ids: list[str], target_folder_id: str) -> list[dict]:
    """批量移动文档到目标文件夹（与用户确认的约束）。

    - 只能移到文件夹：target_folder_id 必填，目标不存在 → FolderNotFoundError（整体失败）
    - 不能跨知识库：doc.kb_id != folder.kb_id → 该 doc rejected
    - 目标文件夹内同名文件 → 该 doc rejected（复用上传同名语义）
    - 已在目标 folder 的 doc 幂等成功（不算错误）
    - 逐文件错误隔离：单个失败不影响其余文档

    移动只改 documents.folder_id：不搬存储对象、不重新解析、不影响已写入的
    向量与分块；folder_path 由列表接口按 folder 树动态拼装，前端刷新即可。
    """
    results: list[dict] = []
    async with get_async_session() as session:
        target = await queries.get_folder(session, target_folder_id)
        if target is None:
            raise folder_svc.FolderNotFoundError(f"目标文件夹不存在：{target_folder_id}")
        for doc_id in doc_ids:
            doc = await queries.get_document(session, doc_id)
            if doc is None:
                results.append({"doc_id": doc_id, "status": "rejected", "error": "文档不存在"})
                continue
            if doc.kb_id != target.kb_id:
                results.append(
                    {
                        "doc_id": doc_id,
                        "status": "rejected",
                        "error": f"不能跨知识库移动：文档属于「{doc.kb_id}」，目标文件夹属于「{target.kb_id}」",
                    }
                )
                continue
            if doc.folder_id == target_folder_id:
                # 已在目标 folder：幂等成功
                results.append({"doc_id": doc_id, "status": "moved"})
                continue
            dup = await queries.find_document_by_folder_name(
                session, target.kb_id, target_folder_id, doc.file_name
            )
            if dup is not None:
                results.append(
                    {
                        "doc_id": doc_id,
                        "status": "rejected",
                        "error": f"目标文件夹已存在同名文件「{doc.file_name}」",
                    }
                )
                continue
            doc.folder_id = target_folder_id
            await session.flush()
            results.append({"doc_id": doc_id, "status": "moved"})
        await session.commit()
    return results


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



async def read_document_file(doc_id: str) -> tuple[dict, bytes]:
    """读取文档原始文件，返回 (doc_dict, bytes)。doc 不存在或原始文件缺失抛 DocumentNotFoundError。"""
    doc = await get_document(doc_id)
    if doc is None:
        raise DocumentNotFoundError(f"文档不存在: {doc_id}")
    if not doc.get("file_path"):
        raise DocumentNotFoundError(f"文档缺少原始文件路径: {doc_id}")
    try:
        data = await asyncio.to_thread(get_storage().get, doc["file_path"])
    except ObjectNotFoundError as exc:
        raise DocumentNotFoundError(f"文档原始文件缺失: {doc_id}") from exc
    return doc, data


async def list_documents(
    kb_id: str | None = None, status: str | None = None
) -> list[dict]:
    async with get_async_session() as session:
        rows = await queries.list_documents(session, kb_id=kb_id, status=status)
        return [_doc_dict(d) for d in rows]


async def count_documents_by_status(*, kb_id: str | None = None) -> dict:
    """按状态统计文档数（轻量，供前端轮询判断是否存在非终态文档）。"""
    async with get_async_session() as session:
        counts = await queries.count_documents_by_status(session, kb_id=kb_id)
    return {
        "total": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "ingesting": counts.get("ingesting", 0),
        "embedding": counts.get("embedding", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "in_progress": (
            counts.get("pending", 0)
            + counts.get("ingesting", 0)
            + counts.get("embedding", 0)
        ),
    }


async def list_documents_paginated(
    *,
    kb_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    folder_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页 + 搜索 + 筛选的文档列表（api 直接返回）。folder_path 由 folder tree 拼装。"""
    async with get_async_session() as session:
        rows, total = await queries.paginate_documents(
            session,
            kb_id=kb_id,
            status=status,
            search=search,
            folder_id=folder_id,
            page=page,
            page_size=page_size,
        )
        # 拼 folder_path（一次取整个 kb 的 folder map，避免每行都查 DB）
        path_map = await folder_svc.get_folder_path_map(kb_id or "default") if rows else {}
        return {
            "items": [
                _doc_dict(d, folder_path=folder_svc.build_folder_path(d.folder_id, path_map))
                for d in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


# ==================== 知识库 ====================

async def list_knowledge_bases() -> list[dict]:
    async with get_async_session() as session:
        kbs = await queries.list_knowledge_bases(session)
        counts = await queries.count_documents_by_kb(session)
        return [_kb_dict(kb, counts.get(kb.kb_id, 0)) for kb in kbs]


async def create_knowledge_base(name: str, description: str = "") -> dict:
    """新建知识库；kb_id 自动生成（uuid 前缀），避免用户侧命名约束。

    同步建一个"默认文件夹"作为文件落入位置（kb 内文件组织根）。
    """
    import uuid

    kb_id = f"kb_{uuid.uuid4().hex[:12]}"
    async with get_async_session() as session:
        kb = await queries.create_knowledge_base(
            session, kb_id, name=name, description=description
        )
        await queries.ensure_default_folder(
            session, kb.kb_id, name=settings.default_kb_folder_name
        )
        return _kb_dict(kb)


async def ensure_default_knowledge_base() -> None:
    """启动时确保默认知识库存在（无则创建），与 auth.ensure_default_admin 对称。

    默认知识库是系统锚点，约定**不可删除**（删除接口对 default 应拒绝）；此处只补缺，
    不覆盖已存在的记录（幂等）。kb_id / name 取自 settings.default_kb_id / default_kb_name。

    顺带为 kb 建一个系统默认 folder（is_system=True，不可删，可改名），用于文件落入。
    """
    async with get_async_session() as session:
        kb = await queries.ensure_knowledge_base(
            session,
            settings.default_kb_id,
            name=settings.default_kb_name,
        )
        await queries.ensure_default_folder(
            session, kb.kb_id, name=settings.default_kb_folder_name
        )


async def migrate_orphan_documents() -> int:
    """启动兜底迁移：``documents.folder_id IS NULL`` 的旧文档 → 该 kb 的默认 folder。

    一次性迁移；运行后所有 documents 应都有 folder_id（除非人为 SQL 改）。
    幂等：第二次调用直接返回。
    """
    from sqlalchemy import func, select, update

    migrated = 0
    async with get_async_session() as session:
        # 先列所有有孤儿文档的 kb_id
        rows = await session.execute(
            select(Document.kb_id, func.count(Document.doc_id))
            .where(Document.folder_id.is_(None))
            .group_by(Document.kb_id)
        )
        orphan_kbs = [kb_id for kb_id, n in rows.all() if kb_id]
        for kb_id in orphan_kbs:
            # 确保该 kb + 默认 folder 都存在
            await queries.ensure_knowledge_base(
                session, kb_id, name=settings.default_kb_name if kb_id == settings.default_kb_id else kb_id
            )
            df = await queries.ensure_default_folder(
                session, kb_id, name=settings.default_kb_folder_name
            )
            # 把孤儿文档归到默认 folder
            stmt = (
                update(Document)
                .where(Document.kb_id == kb_id, Document.folder_id.is_(None))
                .values(folder_id=df.folder_id)
            )
            result = await session.execute(stmt)
            n = int(result.rowcount or 0)
            migrated += n
            if n > 0:
                logger.info("迁移孤儿文档 %d 条 → 默认 folder（kb=%s）", n, kb_id)
    if migrated:
        logger.info("共迁移 %d 条孤儿文档到默认 folder", migrated)
    return migrated
