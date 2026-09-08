"""入库流水线 service（Web 上传与 CLI 批量导入共用）。

阶段：存储原始文件 → 解析 → 分块 → 向量化 → 写 Milvus → 写 DB 原文与元数据。
documents.status 状态机：ingesting → embedding → done；失败 → failed（带 error）。

事件循环保护（单进程 async）：
- 解析（PDF/Office，CPU 密集）、分块（CPU 密集）、Milvus SDK（阻塞 IO）、
  文件存储（阻塞 IO）全部经 ``asyncio.to_thread`` 丢线程池，不阻塞事件循环；
- 只有 BGE-M3 向量化本身是 async（httpx），直接 await。

文件来源统一为 bytes：Web 上传直接给 bytes；CLI 读盘成 bytes。
解析器依赖文件路径，故把 bytes 落临时文件再解析，结束后清理，
从而 Local / MinIO 两种存储后端走完全相同的路径。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.db import get_async_session
from app.models import queries
from app.services import doc_states
from app.services.chunker import Chunk, chunk_document
from app.services.parsers import parse_file
from app.services.parsers.base import ParsedDocument
from app.services.storage import FileStorage, get_storage

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class IngestResult:
    """单文档入库结果。"""

    file_name: str
    doc_id: str
    kb_id: str
    status: str  # done / skipped / failed
    chunks: int = 0
    table_chunks: int = 0
    page_count: int = 0
    elapsed: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done"


def make_doc_id(file_name: str) -> str:
    """文档 id：文件名哈希，同一文件重复入库 id 不变（幂等）。"""
    return hashlib.md5(Path(file_name).name.encode("utf-8")).hexdigest()[:16]


def storage_key(kb_id: str, doc_id: str, file_name: str) -> str:
    """对象存储 key：{kb_id}/{doc_id}/{原始文件名}。"""
    return f"{kb_id}/{doc_id}/{Path(file_name).name}"


async def _mark(doc_id: str, target: str, **fields) -> None:
    """分阶段落库状态（独立事务即时 commit，崩溃后可凭状态恢复）。

    写入前先经状态机校验，非法跳转直接抛 IllegalTransitionError，不留脏状态。
    """
    async with get_async_session() as session:
        current = await queries.document_status(session, doc_id)
        doc_states.assert_transition(current, target)
        await queries.upsert_document(session, doc_id=doc_id, status=target, **fields)


async def ingest_bytes(
    data: bytes,
    file_name: str,
    *,
    kb_id: str | None = None,
    embedder=None,
    store=None,
    storage: FileStorage | None = None,
    force: bool = False,
    doc_id: str | None = None,
) -> IngestResult:
    """入库一个文档的字节内容。Web 上传与 CLI 的统一入口。

    参数 embedder/store 延迟到此处注入，避免模块导入期就连接外部服务。
    """
    kb_id = kb_id or settings.default_kb_id
    doc_id = doc_id or make_doc_id(file_name)
    storage = storage or get_storage()
    t0 = time.perf_counter()

    def result(status: str, **kw) -> IngestResult:
        return IngestResult(
            file_name=file_name,
            doc_id=doc_id,
            kb_id=kb_id,
            status=status,
            elapsed=time.perf_counter() - t0,
            **kw,
        )

    # ---- 0. 确保知识库存在 + 断点续传判断 ----
    async with get_async_session() as session:
        await queries.ensure_knowledge_base(
            session, kb_id, name=settings.default_kb_name if kb_id == settings.default_kb_id else kb_id
        )
        if not force:
            st = await queries.document_status(session, doc_id)
            if st == "done":
                logger.info("跳过（已完成）: %s", file_name)
                return result("skipped")

    # ---- 1. 原始文件入对象存储 ----
    key = storage_key(kb_id, doc_id, file_name)
    await asyncio.to_thread(storage.put, key, data)

    await _mark(
        doc_id,
        "ingesting",
        kb_id=kb_id,
        file_name=Path(file_name).name,
        file_path=key,
        file_ext=Path(file_name).suffix.lower(),
        file_size=len(data),
        error="",
    )

    # ---- 2. 落临时文件 → 线程池解析（CPU 密集）----
    suffix = Path(file_name).suffix
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        parsed: ParsedDocument = await asyncio.to_thread(parse_file, tmp_path, doc_id)
        if not parsed.ok:
            await _mark(doc_id, "failed", error=parsed.error)
            logger.error("解析失败 %s: %s", file_name, parsed.error)
            return result("failed", error=parsed.error)
        # 解析器用临时文件名，这里还原成真实文件名
        parsed.file_name = Path(file_name).name

        # ---- 3. 线程池分块（CPU 密集）----
        chunks: list[Chunk] = await asyncio.to_thread(chunk_document, parsed)
        if not chunks:
            err = "未分出任何 chunk"
            await _mark(doc_id, "failed", error=err)
            return result("failed", error=err)

        table_chunks = sum(1 for c in chunks if c.is_table)
        await _mark(
            doc_id,
            "embedding",
            page_count=parsed.page_count,
            chunk_count=len(chunks),
            table_chunks=table_chunks,
        )
        logger.info(
            "%s：%d 页 → %d chunk（表格 %d）",
            file_name, parsed.page_count, len(chunks), table_chunks,
        )

        # ---- 4. 分批向量化（async）+ 分批写 Milvus（线程池）----
        # 首次入库或清库后场景：集合不存在则建（drop_if_exists=False，已存在则跳过）。
        # 见 vectorstore.delete_by_doc 的注释——defense in depth，两道关都设。
        await asyncio.to_thread(store.ensure_collection)
        # 先清旧向量保证幂等（重新入库场景）
        await asyncio.to_thread(store.delete_by_doc, doc_id, kb_id)

        batch = settings.embed_max_batch
        for start in range(0, len(chunks), batch):
            group = chunks[start : start + batch]
            res = await embedder.embed([c.full_text for c in group])
            rows = [
                {
                    "chunk_id": c.chunk_id,
                    "kb_id": kb_id,
                    "doc_id": c.doc_id,
                    "doc_name": c.doc_name,
                    "text": c.full_text,
                    "page": c.page,
                    "dense": res.dense[i],
                    "sparse": res.sparse[i],
                }
                for i, c in enumerate(group)
            ]
            await asyncio.to_thread(store.insert, rows)
            logger.info("  已写入 %d/%d", min(start + batch, len(chunks)), len(chunks))

        # ---- 5. 写 DB 原文 + 文档 done（同一事务，保证 chunks 与 done 原子）----
        async with get_async_session() as session:
            current = await queries.document_status(session, doc_id)
            doc_states.assert_transition(current, doc_states.DONE)
            await queries.replace_chunks(
                session,
                doc_id=doc_id,
                kb_id=kb_id,
                chunks=[
                    {
                        "chunk_id": c.chunk_id,
                        "index": c.index,
                        "page": c.page,
                        "heading_path": c.heading_path,
                        "is_table": c.is_table,
                        "text": c.text,
                    }
                    for c in chunks
                ],
            )
            await queries.upsert_document(
                session,
                doc_id=doc_id,
                status="done",
                error="",
                page_count=parsed.page_count,
                chunk_count=len(chunks),
                table_chunks=table_chunks,
            )

        logger.info("完成 %s：%d chunk，耗时 %.1fs", file_name, len(chunks), time.perf_counter() - t0)
        return result(
            "done",
            chunks=len(chunks),
            table_chunks=table_chunks,
            page_count=parsed.page_count,
        )

    except Exception as e:  # noqa: BLE001 流水线兜底：异常落 failed 状态
        logger.exception("入库异常 %s", file_name)
        try:
            await _mark(doc_id, "failed", error=f"{type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001 状态落库失败不掩盖原始异常
            pass
        return result("failed", error=f"{type(e).__name__}: {e}")
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


async def ingest_path(
    path: Path | str,
    *,
    kb_id: str | None = None,
    embedder=None,
    store=None,
    storage: FileStorage | None = None,
    force: bool = False,
) -> IngestResult:
    """CLI 便利入口：读本地文件为 bytes 后走统一流水线。"""
    path = Path(path)
    data = await asyncio.to_thread(path.read_bytes)
    return await ingest_bytes(
        data,
        path.name,
        kb_id=kb_id,
        embedder=embedder,
        store=store,
        storage=storage,
        force=force,
    )
