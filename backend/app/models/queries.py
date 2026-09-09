"""ORM 查询/写入函数（轻量收拢，不做 repository 抽象）。

约定：
- 所有函数接收 ``AsyncSession``，内部只 ``flush`` 不 ``commit``，
  事务边界由调用方（db.get_async_session 上下文）统一控制，
  便于 ingestion 分阶段落库、service 组合多步操作。
- 这是"可复用、可单测的函数集合"，不是一接口多实现的 repository；
  换库由 SQLAlchemy 方言层覆盖，无需额外抽象。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.folder import Folder
from app.models.knowledge_base import KnowledgeBase
from app.models.log import QueryLog


# ==================== 知识库 ====================

async def ensure_knowledge_base(
    session: AsyncSession, kb_id: str, name: str | None = None
) -> KnowledgeBase:
    """知识库不存在则创建，返回已存在或新建的实例。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        kb = KnowledgeBase(kb_id=kb_id, name=name or kb_id, description="")
        session.add(kb)
        await session.flush()
    return kb


async def create_knowledge_base(
    session: AsyncSession, kb_id: str, name: str, description: str = ""
) -> KnowledgeBase:
    """新建知识库（kb_id 唯一，已存在则原样返回）。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        kb = KnowledgeBase(kb_id=kb_id, name=name, description=description)
        session.add(kb)
        await session.flush()
    return kb


async def list_knowledge_bases(session: AsyncSession) -> list[KnowledgeBase]:
    stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_documents_by_kb(session: AsyncSession) -> dict[str, int]:
    """各知识库的文档数（统计展示用）。"""
    rows = await session.execute(
        select(Document.kb_id, func.count(Document.doc_id)).group_by(Document.kb_id)
    )
    return {kb_id: int(n) for kb_id, n in rows.all()}


async def count_documents_by_folder(session: AsyncSession, kb_id: str) -> dict[str, int]:
    """某 kb 下各 folder 的文档数（folder 内嵌计数用）。folder_id=None 统计无 folder 文件。"""
    rows = await session.execute(
        select(Document.folder_id, func.count(Document.doc_id))
        .where(Document.kb_id == kb_id)
        .group_by(Document.folder_id)
    )
    return {fid: int(n) for fid, n in rows.all() if fid is not None or True}


# ==================== 文件夹 ====================

def make_folder_id() -> str:
    """文件夹 id：``f_`` 前缀 + uuid12 位，便于与 kb_/ 区分。"""
    return f"f_{uuid.uuid4().hex[:12]}"


async def get_folder(session: AsyncSession, folder_id: str) -> Folder | None:
    return await session.get(Folder, folder_id)


async def get_default_folder(session: AsyncSession, kb_id: str) -> Folder | None:
    """某 kb 的系统默认 folder（is_system=True）。"""
    stmt = (
        select(Folder)
        .where(Folder.kb_id == kb_id)
        .where(Folder.parent_id.is_(None))
        .where(Folder.is_system.is_(True))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def ensure_default_folder(
    session: AsyncSession, kb_id: str, name: str = "默认文件夹"
) -> Folder:
    """某 kb 的默认 folder：无则建（系统保护 is_system=True，不可删除）。"""
    existing = await get_default_folder(session, kb_id)
    if existing is not None:
        return existing
    folder = Folder(
        folder_id=make_folder_id(),
        kb_id=kb_id,
        parent_id=None,
        name=name,
        depth=1,
        is_system=True,
    )
    session.add(folder)
    await session.flush()
    return folder


async def create_folder(
    session: AsyncSession,
    *,
    kb_id: str,
    parent_id: str | None,
    name: str,
    depth: int,
    is_system: bool = False,
) -> Folder:
    """新建 folder；唯一性 / 深度由 service 层校验。"""
    folder = Folder(
        folder_id=make_folder_id(),
        kb_id=kb_id,
        parent_id=parent_id,
        name=name,
        depth=depth,
        is_system=is_system,
    )
    session.add(folder)
    await session.flush()
    return folder


async def list_folders_by_kb(session: AsyncSession, kb_id: str) -> list[Folder]:
    """列某 kb 下所有 folder（含顶层 + 子 folder），树构建交给 service 层。"""
    stmt = select(Folder).where(Folder.kb_id == kb_id).order_by(Folder.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def list_folders_by_parent(
    session: AsyncSession, kb_id: str, parent_id: str | None
) -> list[Folder]:
    """列某 folder 下直属子 folder（拖拽校验 / 列表用）。"""
    stmt = select(Folder).where(Folder.kb_id == kb_id)
    if parent_id is None:
        stmt = stmt.where(Folder.parent_id.is_(None))
    else:
        stmt = stmt.where(Folder.parent_id == parent_id)
    return list((await session.execute(stmt)).scalars().all())


async def find_folder_by_sibling_name(
    session: AsyncSession, kb_id: str, parent_id: str | None, name: str
) -> Folder | None:
    """同 parent 下查找同名 folder（service 层用于"重名拒绝"）。"""
    stmt = select(Folder).where(
        Folder.kb_id == kb_id,
        Folder.name == name,
    )
    stmt = stmt.where(
        Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id
    )
    return (await session.execute(stmt)).scalars().first()


async def find_document_by_folder_name(
    session: AsyncSession, kb_id: str, folder_id: str, file_name: str
) -> Document | None:
    """同 folder 下查找同名 document（service 层用于"重名拒绝"）。"""
    stmt = select(Document).where(
        Document.kb_id == kb_id,
        Document.folder_id == folder_id,
        Document.file_name == file_name,
    )
    return (await session.execute(stmt)).scalars().first()


async def list_doc_ids_by_folders(
    session: AsyncSession, folder_ids: list[str]
) -> list[str]:
    """某批 folder 下（含子 folder）所有文档 doc_id（级联删除时取账本用）。"""
    if not folder_ids:
        return []
    stmt = select(Document.doc_id).where(Document.folder_id.in_(folder_ids))
    return [r for r, in (await session.execute(stmt)).all()]


async def collect_descendant_folder_ids(
    session: AsyncSession, root_ids: list[str]
) -> list[str]:
    """BFS 收集 root_ids 所有子孙 folder_id（含自身）。用于级联删除时一次取出所有相关 doc_id。"""
    if not root_ids:
        return []
    all_ids: set[str] = set(root_ids)
    frontier: list[str] = list(root_ids)
    while frontier:
        stmt = select(Folder.folder_id).where(Folder.parent_id.in_(frontier))
        children = [r for r, in (await session.execute(stmt)).all()]
        new = [c for c in children if c not in all_ids]
        if not new:
            break
        all_ids.update(new)
        frontier = new
    return sorted(all_ids)


async def rename_folder(session: AsyncSession, folder: Folder, new_name: str) -> Folder:
    """重命名；同 parent 下同名由 service 层校验。"""
    folder.name = new_name
    folder.updated_at = time.time()
    await session.flush()
    return folder


async def move_folder(
    session: AsyncSession, folder: Folder, new_parent_id: str | None
) -> Folder:
    """拖拽移动：仅改 parent_id；新 parent 同 kb 与新深度由 service 层校验。"""
    folder.parent_id = new_parent_id
    folder.updated_at = time.time()
    await session.flush()
    return folder


async def delete_folder_rows(session: AsyncSession, folder_ids: list[str]) -> int:
    """删 folder 记录（不含 files，files 由 service 层走删除补偿）。"""
    if not folder_ids:
        return 0
    result = await session.execute(delete(Folder).where(Folder.folder_id.in_(folder_ids)))
    await session.flush()
    return result.rowcount or 0


async def unset_folder_for_docs(
    session: AsyncSession, doc_ids: list[str]
) -> int:
    """把指定文档的 folder_id 置 NULL（用于 folder 删除时级联清账前的临时操作），
    避免外键约束阻止删除 folder；实际文档记录由 doc_service.delete_document 删除。"""
    if not doc_ids:
        return 0
    result = await session.execute(
        Document.__table__.update()
        .where(Document.doc_id.in_(doc_ids))
        .values(folder_id=None)
    )
    await session.flush()
    return result.rowcount or 0


# ==================== 文档 ====================

async def get_document(session: AsyncSession, doc_id: str) -> Document | None:
    return await session.get(Document, doc_id)


async def document_status(session: AsyncSession, doc_id: str) -> str | None:
    doc = await session.get(Document, doc_id)
    return doc.status if doc else None


async def upsert_document(session: AsyncSession, *, doc_id: str, **fields: Any) -> Document:
    """新增或更新文档记录，自动维护 updated_at。"""
    now = time.time()
    doc = await session.get(Document, doc_id)
    if doc is not None:
        for key, value in fields.items():
            setattr(doc, key, value)
        doc.updated_at = now
    else:
        doc = Document(doc_id=doc_id, created_at=now, updated_at=now, **fields)
        session.add(doc)
    await session.flush()
    return doc


async def list_documents(
    session: AsyncSession, kb_id: str | None = None, status: str | None = None,
    folder_id: str | None = None,
) -> list[Document]:
    stmt = select(Document)
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    if folder_id:
        stmt = stmt.where(Document.folder_id == folder_id)
    if status:
        stmt = stmt.where(Document.status == status)
    stmt = stmt.order_by(Document.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def paginate_documents(
    session: AsyncSession,
    *,
    kb_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    folder_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    """分页 + 文件名模糊搜索 + 状态筛选 + folder 过滤的文档列表；返回 (items, total)。"""
    conds = []
    if kb_id:
        conds.append(Document.kb_id == kb_id)
    if folder_id:
        conds.append(Document.folder_id == folder_id)
    if status:
        conds.append(Document.status == status)
    if search:
        conds.append(Document.file_name.ilike(f"%{search}%"))
    where = None
    for c in conds:
        where = c if where is None else where & c

    base = select(Document)
    count_stmt = select(func.count(Document.doc_id))
    if where is not None:
        base = base.where(where)
        count_stmt = count_stmt.where(where)

    total = (await session.execute(count_stmt)).scalar() or 0
    stmt = base.order_by(Document.updated_at.desc())
    if page_size > 0:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    return list(result.scalars().all()), int(total)


async def delete_document_rows(session: AsyncSession, doc_id: str) -> None:
    """删除文档的 DB 记录及其全部 chunk 原文（不含向量/文件，那是补偿流程的事）。"""
    await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    await session.execute(delete(Document).where(Document.doc_id == doc_id))
    await session.flush()


async def count_documents_by_status(
    session: AsyncSession,
    *,
    kb_id: str | None = None,
) -> dict[str, int]:
    """按状态统计文档数（单条 GROUP BY，供轮询判断是否存在非终态文档）。"""
    stmt = select(Document.status, func.count(Document.doc_id))
    if kb_id:
        stmt = stmt.where(Document.kb_id == kb_id)
    stmt = stmt.group_by(Document.status)
    rows = await session.execute(stmt)
    counts: dict[str, int] = {}
    for status, n in rows.all():
        counts[status] = int(n)
    return counts


async def list_stuck_documents(
    session: AsyncSession, statuses: set[str], before_ts: float
) -> list[Document]:
    """找处于给定处理态、且 updated_at 早于 before_ts 的文档（启动卡死恢复用）。"""
    if not statuses:
        return []
    stmt = (
        select(Document)
        .where(Document.status.in_(statuses))
        .where(Document.updated_at < before_ts)
        .order_by(Document.updated_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ==================== 分块原文 ====================

async def replace_chunks(
    session: AsyncSession, doc_id: str, kb_id: str, chunks: list[dict[str, Any]]
) -> int:
    """整篇替换分块原文：先清旧再插新，避免重新入库残留脏数据。"""
    await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    now = time.time()
    session.add_all(
        [
            Chunk(
                chunk_id=c["chunk_id"],
                doc_id=doc_id,
                kb_id=kb_id,
                chunk_index=c["index"],
                page=c.get("page", 0),
                heading_path=c.get("heading_path", ""),
                is_table=int(bool(c.get("is_table"))),
                text=c["text"],
                created_at=now,
            )
            for c in chunks
        ]
    )
    await session.flush()
    return len(chunks)


async def get_chunks_by_ids(session: AsyncSession, chunk_ids: list[str]) -> list[Chunk]:
    """按 chunk_id 批量取原文，保持传入顺序。"""
    if not chunk_ids:
        return []
    result = await session.execute(select(Chunk).where(Chunk.chunk_id.in_(chunk_ids)))
    by_id = {c.chunk_id: c for c in result.scalars().all()}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]


# ==================== 统计 ====================

async def stats(session: AsyncSession) -> dict[str, int]:
    docs = (await session.execute(select(func.count(Document.doc_id)))).scalar() or 0
    chunks = (await session.execute(select(func.count(Chunk.chunk_id)))).scalar() or 0
    tables = (
        await session.execute(
            select(func.count(Chunk.chunk_id)).where(Chunk.is_table == 1)
        )
    ).scalar() or 0
    chars = (
        await session.execute(select(func.coalesce(func.sum(func.length(Chunk.text)), 0)))
    ).scalar() or 0
    return {
        "documents": int(docs),
        "chunks": int(chunks),
        "table_chunks": int(tables),
        "total_chars": int(chars),
    }


# ==================== 会话 ====================

async def create_conversation(
    session: AsyncSession,
    conv_id: str,
    kb_id: str = "default",
    title: str = "",
    mode: str = "kb",
    user_id: str = "",
) -> Conversation:
    now = time.time()
    conv = Conversation(
        id=conv_id, kb_id=kb_id, mode=mode, title=title, user_id=user_id,
        created_at=now, updated_at=now,
    )
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, conv_id: str) -> Conversation | None:
    return await session.get(Conversation, conv_id)


async def list_conversations(
    session: AsyncSession,
    kb_id: str | None = None,
    mode: str | None = None,
    user_id: str | None = None,
) -> list[Conversation]:
    stmt = select(Conversation)
    if kb_id:
        stmt = stmt.where(Conversation.kb_id == kb_id)
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    stmt = stmt.order_by(Conversation.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def touch_conversation(session: AsyncSession, conv_id: str, title: str | None = None) -> None:
    """更新会话的最近活跃时间；title 非空且原标题为空时用它补标题。"""
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return
    conv.updated_at = time.time()
    if title and not conv.title:
        conv.title = title[:40]
    await session.flush()


async def rename_conversation(session: AsyncSession, conv_id: str, title: str) -> Conversation | None:
    """覆盖会话标题并刷新 updated_at；不存在返回 None（供上层映射 404）。"""
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return None
    conv.title = title[:40]
    conv.updated_at = time.time()
    await session.flush()
    return conv


async def delete_conversation_rows(session: AsyncSession, conv_id: str) -> None:
    """删除会话及其全部消息（query_logs 保留作统计，仅断开关联）。"""
    await session.execute(delete(Message).where(Message.conversation_id == conv_id))
    await session.execute(delete(Conversation).where(Conversation.id == conv_id))
    await session.flush()


# ==================== 消息 ====================

async def add_message(
    session: AsyncSession,
    *,
    message_id: str,
    conversation_id: str,
    role: str,
    content: str,
    refs_json: str = "[]",
    created_at: float | None = None,
) -> Message:
    msg = Message(
        id=message_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        refs_json=refs_json,
        created_at=created_at if created_at is not None else time.time(),
    )
    session.add(msg)
    await session.flush()
    return msg


async def list_messages(
    session: AsyncSession, conversation_id: str, limit: int | None = None
) -> list[Message]:
    """取会话消息，按时间正序返回；limit 非空时先取最近 limit 条再转正序（拼历史用）。"""
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if limit:
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows
    stmt = stmt.order_by(Message.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


# ==================== 查询日志 ====================

async def add_query_log(
    session: AsyncSession,
    *,
    log_id: str,
    conversation_id: str = "",
    kb_id: str = "default",
    mode: str = "kb",
    user_id: str = "",
    question: str = "",
    answer: str = "",
    hit_count: int = 0,
    refs_json: str = "[]",
    retrieval_ms: float = 0.0,
    llm_ms: float = 0.0,
    total_ms: float = 0.0,
    created_at: float | None = None,
) -> QueryLog:
    log = QueryLog(
        id=log_id,
        conversation_id=conversation_id,
        kb_id=kb_id,
        mode=mode,
        user_id=user_id,
        question=question,
        answer=answer,
        hit_count=hit_count,
        refs_json=refs_json,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        total_ms=total_ms,
        created_at=created_at if created_at is not None else time.time(),
    )
    session.add(log)
    await session.flush()
    return log


# ==================== 数据统计 ====================

async def stats_summary(
    session: AsyncSession,
    *,
    days: int | None = None,
    mode: str = "all",
) -> dict[str, Any]:
    """问答统计聚合（数据统计页，单接口一次返回全部）。

    - days：None 全量；否则 created_at >= now - days 天；
    - mode：all 不过滤 / kb（知识库问答）/ general（通用问答）；
    - top_docs 从 refs_json 解析 doc_name，同一问答引用同一文档只计 1 次。
    """
    now = time.time()
    # 近 N 个自然日（含今天）：起始 = 今天 - (days-1) 的 0 点；days=None 全量
    if days:
        start_date = datetime.now().date() - timedelta(days=days - 1)
        since = datetime.combine(start_date, datetime.min.time()).timestamp()
    else:
        since = 0.0
    stmt = select(QueryLog).where(QueryLog.created_at >= since)
    if mode in ("kb", "general"):
        stmt = stmt.where(QueryLog.mode == mode)
    rows = (await session.execute(stmt)).scalars().all()

    total = len(rows)
    hit_count = sum(1 for r in rows if r.hit_count > 0)
    no_hit = total - hit_count
    hit_rate = hit_count / total * 100 if total else 0.0
    avg_retrieval = sum(r.retrieval_ms for r in rows) / total if total else 0.0
    avg_llm = sum(r.llm_ms for r in rows) / total if total else 0.0
    avg_total = sum(r.total_ms for r in rows) / total if total else 0.0

    # 按天聚合：{date: [count, hit, total_ms_sum]}
    by_day: dict[str, list] = {}
    for r in rows:
        d = datetime.fromtimestamp(r.created_at).date().isoformat()
        b = by_day.setdefault(d, [0, 0, 0.0])
        b[0] += 1
        if r.hit_count > 0:
            b[1] += 1
        b[2] += r.total_ms

    def _trend_point(d: str, b: list) -> dict[str, Any]:
        return {
            "date": d,
            "count": b[0],
            "hit_rate": round(b[1] / b[0] * 100, 1) if b[0] else 0.0,
            "avg_total_ms": round(b[2] / b[0], 1) if b[0] else 0.0,
        }

    trend: list[dict[str, Any]] = []
    if days:
        cursor = start_date
        end = datetime.now().date()
        while cursor <= end:
            d = cursor.isoformat()
            trend.append(_trend_point(d, by_day.get(d, [0, 0, 0.0])))
            cursor += timedelta(days=1)
    else:
        for d in sorted(by_day):
            trend.append(_trend_point(d, by_day[d]))

    # 高频问题 Top10
    qcount: dict[str, int] = {}
    for r in rows:
        q = r.question.strip() or "(空问题)"
        qcount[q] = qcount.get(q, 0) + 1
    top_questions = [
        {"question": k, "count": v}
        for k, v in sorted(qcount.items(), key=lambda x: (-x[1], x[0]))[:10]
    ]

    # Top 引用文档 Top10（Python 侧解析，规避 SQLite JSON 方言差异）
    dcount: dict[str, int] = {}
    for r in rows:
        if not r.refs_json:
            continue
        try:
            refs = json.loads(r.refs_json)
        except (ValueError, TypeError):
            continue
        seen: set[str] = set()
        for ref in refs:
            name = (ref or {}).get("doc_name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            dcount[name] = dcount.get(name, 0) + 1
    top_docs = [
        {"doc_name": k, "count": v}
        for k, v in sorted(dcount.items(), key=lambda x: (-x[1], x[0]))[:10]
    ]

    # kb 分布
    kbcount: dict[str, int] = {}
    for r in rows:
        k = r.kb_id or "default"
        kbcount[k] = kbcount.get(k, 0) + 1
    kb_dist = [
        {"kb_id": k, "count": v}
        for k, v in sorted(kbcount.items(), key=lambda x: (-x[1], x[0]))
    ]

    return {
        "cards": {
            "total": total,
            "hit_count": hit_count,
            "hit_rate": round(hit_rate, 1),
            "avg_retrieval_ms": round(avg_retrieval, 1),
            "avg_llm_ms": round(avg_llm, 1),
            "avg_total_ms": round(avg_total, 1),
            "no_hit_count": no_hit,
        },
        "trend": trend,
        "top_questions": top_questions,
        "top_docs": top_docs,
        "kb_dist": kb_dist,
    }
