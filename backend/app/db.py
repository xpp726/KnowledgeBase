"""数据访问层。

过渡期两部分并存：
- 新：SQLAlchemy 2.0 async engine/session（models/ 下 ORM 模型使用，Alembic 管 schema）
- 旧：裸 sqlite3 函数（scripts/ingest.py 等暂用，后续逐步迁移到 models/queries）

向量与相似度检索全部交给 Milvus，本层只存结构化元数据和 chunk 原文。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ==================== 新：SQLAlchemy 2.0 async ====================

# create_async_engine 是懒连接，模块级创建无副作用；方言由 database_url 决定
async_engine = create_async_engine(
    settings.resolved_database_url,
    echo=settings.db_echo,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用的 async session，自动 commit/rollback。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """开发期便捷建表（CREATE TABLE IF NOT EXISTS 语义，不影响已存在的表）。

    生产环境 schema 演进一律走 Alembic（alembic upgrade head），本函数仅供
    CLI 脚本开箱即用与测试，不处理列变更。
    """
    from app.models import Base  # 局部导入避免循环依赖

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_schema_patches() -> None:
    """SQLite 过渡期的轻量列迁移（幂等，每次启动执行）。

    MySQL 阶段由 Alembic 管理，本函数仅覆盖开发期 SQLite 加列场景。
    """
    from sqlalchemy import text

    async with async_engine.begin() as conn:
        # conversations.mode：问答模式列（历史会话默认 kb，零丢失）
        rows = await conn.execute(
            text(
                "SELECT name FROM pragma_table_info('conversations') "
                "WHERE name = 'mode'"
            )
        )
        if rows.fetchone() is None:
            await conn.execute(
                text(
                    "ALTER TABLE conversations "
                    "ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'kb'"
                )
            )
            logger.info("迁移：conversations 增加 mode 列（默认 kb）")
        # query_logs.mode：问答口径列（历史日志默认 kb，零丢失）
        rows = await conn.execute(
            text(
                "SELECT name FROM pragma_table_info('query_logs') "
                "WHERE name = 'mode'"
            )
        )
        if rows.fetchone() is None:
            await conn.execute(
                text(
                    "ALTER TABLE query_logs "
                    "ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'kb'"
                )
            )
            logger.info("迁移：query_logs 增加 mode 列（默认 kb）")


# ==================== 旧：裸 sqlite3（legacy，将迁移到 models/queries） ====================

SCHEMA = """
-- 文档
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    file_name    TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    file_ext     TEXT NOT NULL DEFAULT '',
    file_size    INTEGER NOT NULL DEFAULT 0,
    page_count   INTEGER NOT NULL DEFAULT 0,
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    table_chunks INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT DEFAULT '',
    created_at   REAL,
    updated_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

-- 分块原文（向量在 Milvus，原文在这里）
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,
    page         INTEGER NOT NULL DEFAULT 0,
    heading_path TEXT NOT NULL DEFAULT '',
    is_table     INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL,
    created_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

-- 会话
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  REAL,
    updated_at  REAL
);

-- 消息
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    refs_json       TEXT NOT NULL DEFAULT '[]',
    created_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);

-- 查询日志（阶段 3 统计报表用）
CREATE TABLE IF NOT EXISTS query_logs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT DEFAULT '',
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL DEFAULT '',
    hit_count       INTEGER NOT NULL DEFAULT 0,
    refs_json       TEXT NOT NULL DEFAULT '[]',
    retrieval_ms    REAL NOT NULL DEFAULT 0,
    llm_ms          REAL NOT NULL DEFAULT 0,
    total_ms        REAL NOT NULL DEFAULT 0,
    created_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON query_logs(created_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.sqlite_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取连接，自动提交/回滚/关闭。"""
    settings.ensure_dirs()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表（幂等）。legacy 路径，新代码用 Alembic。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info("SQLite 初始化完成: %s", settings.sqlite_path)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:24]}"


# ---------- 文档 ----------
def upsert_document(
    doc_id: str,
    file_name: str,
    file_path: str | Path,
    file_ext: str = "",
    file_size: int = 0,
    status: str = "pending",
    **extra: Any,
) -> None:
    """新增或更新文档记录。"""
    now = time.time()
    fields = {
        "doc_id": doc_id,
        "file_name": file_name,
        "file_path": str(file_path),
        "file_ext": file_ext,
        "file_size": file_size,
        "status": status,
        "updated_at": now,
        **extra,
    }
    cols = list(fields)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT doc_id FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{c} = ?" for c in cols if c != "doc_id")
            conn.execute(
                f"UPDATE documents SET {sets} WHERE doc_id = ?",
                [fields[c] for c in cols if c != "doc_id"] + [doc_id],
            )
        else:
            fields["created_at"] = now
            cols = list(fields)
            placeholders = ", ".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO documents ({', '.join(cols)}) VALUES ({placeholders})",
                [fields[c] for c in cols],
            )


def get_document(doc_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row else None


def list_documents(status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM documents"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY updated_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def delete_document(doc_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


# ---------- 分块 ----------
def replace_chunks(doc_id: str, chunks: list[dict[str, Any]]) -> int:
    """整篇替换分块（重新入库时先清旧的，避免残留脏数据）。"""
    now = time.time()
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            "INSERT INTO chunks (chunk_id, doc_id, chunk_index, page, "
            "heading_path, is_table, text, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    c["chunk_id"], doc_id, c["index"], c.get("page", 0),
                    c.get("heading_path", ""), int(bool(c.get("is_table"))),
                    c["text"], now,
                )
                for c in chunks
            ],
        )
    return len(chunks)


def get_chunks(chunk_ids: list[str]) -> list[dict[str, Any]]:
    """按 chunk_id 批量取原文，用于检索后回填引用。保持传入顺序。"""
    if not chunk_ids:
        return []
    placeholders = ", ".join("?" * len(chunk_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})", chunk_ids
        ).fetchall()
    by_id = {r["chunk_id"]: dict(r) for r in rows}
    return [by_id[c] for c in chunk_ids if c in by_id]


def stats() -> dict[str, int]:
    with get_conn() as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        tables = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE is_table = 1"
        ).fetchone()[0]
        chars = conn.execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM chunks").fetchone()[0]
    return {
        "documents": docs,
        "chunks": chunks,
        "table_chunks": tables,
        "total_chars": chars,
    }
