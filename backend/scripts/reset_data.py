# -*- coding: utf-8 -*-
"""一键清空数据环境：MySQL 业务表 + Milvus 向量集合 + 对象存储（MinIO/local）。

用法（在 backend 目录、虚拟环境已激活）：
    python scripts/reset_data.py                 # 交互确认后执行
    python scripts/reset_data.py --yes           # 跳过交互确认（CI / 无人值守）
    python scripts/reset_data.py --dry-run       # 只打印将删除的内容，不执行任何删除
    python scripts/reset_data.py --keep-db       # 跳过 MySQL
    python scripts/reset_data.py --keep-milvus   # 跳过向量库
    python scripts/reset_data.py --keep-storage  # 跳过对象存储
    python scripts/reset_data.py --no-rebuild    # 清表后不自动跑 alembic upgrade head

执行后：
    - MySQL  ：删除当前库（DATABASE()）下全部业务表（含 alembic_version），
               随后自动执行 `alembic upgrade head` 重建全部表结构（--no-rebuild 可跳过）
    - Milvus ：删除并重建空集合（上传文档时 ingestion 也会自动 ensure_collection）
    - 存储   ：删除 bucket（MinIO）/ 上传目录（local）下全部对象；bucket 缺失时后端启动自动创建

⚠️  请在确认【后端服务已停止】后运行，否则运行中的请求会因表不存在而报错。
    此操作不可恢复，请先备份需要保留的数据。
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.infrastructure.database.session import async_engine  # noqa: E402
from app.infrastructure.storage.provider import get_storage  # noqa: E402
from app.infrastructure.vectorstore.milvus import get_vectorstore  # noqa: E402

settings = get_settings()


def _ask(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")


async def reset_database(dry_run: bool) -> list[str]:
    """删除当前 MySQL 库下全部表（含 alembic_version）。返回表名列表。"""
    async with async_engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ).fetchall()
    tables = [r[0] for r in rows]
    if not tables:
        print("  [DB] 当前库没有任何表，跳过")
        return []
    print(f"  [DB] 将删除 {len(tables)} 张表：{', '.join(sorted(tables))}")
    if not dry_run:
        async with async_engine.begin() as conn:
            for t in tables:
                await conn.execute(text(f"DROP TABLE IF EXISTS `{t}`"))
        print("  [DB] 全部表已删除")
    return tables


async def reset_milvus(dry_run: bool) -> None:
    """删除 Milvus 集合并重建为空集合（drop_if_exists=True）。"""
    store = get_vectorstore()
    if not store.has_collection():
        print(f"  [Milvus] 集合 {store.collection} 不存在，跳过")
        return
    print(f"  [Milvus] 将删除集合并重建为空集合：{store.collection}")
    if not dry_run:
        # ensure_collection(drop_if_exists=True)：先 drop 旧集合，再按新 schema 重建（无数据）
        await asyncio.to_thread(store.ensure_collection, True)
        print("  [Milvus] 已删除并重建空集合")


async def reset_storage(dry_run: bool) -> None:
    """删除对象存储（MinIO bucket / 本地上传目录）下全部对象。"""
    storage = get_storage()
    keys = storage.list_keys()
    label = (
        f"bucket={settings.minio_bucket}"
        if settings.storage_backend.lower() == "minio"
        else f"目录={settings.upload_dir}"
    )
    if not keys:
        print(f"  [Storage] 存储为空（{label}），跳过")
        return
    print(f"  [Storage] 将删除 {len(keys)} 个对象（{label}）")
    if not dry_run:
        for k in keys:
            storage.delete(k)
        print("  [Storage] 已清空全部对象")


def rebuild_schema() -> None:
    """清表后用 alembic 重建全部表结构（cwd 必须是 backend 根，alembic.ini 在那里）。"""
    backend_dir = Path(__file__).resolve().parent.parent
    print("  [DB] 正在执行 alembic upgrade head 重建表结构…")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        check=True,
    )
    print("  [DB] 表结构重建完成")


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="一键清空数据环境（MySQL 业务表 + Milvus 向量 + 对象存储）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/reset_data.py --dry-run       # 预览将删除的内容\n"
            "  python scripts/reset_data.py --yes           # 确认后全部清空并重建表结构\n"
            "  python scripts/reset_data.py --yes --keep-milvus --keep-storage  # 只清数据库\n"
        ),
    )
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--dry-run", action="store_true", help="只打印将删除的内容，不执行")
    ap.add_argument("--keep-db", action="store_true", help="跳过 MySQL")
    ap.add_argument("--keep-milvus", action="store_true", help="跳过 Milvus")
    ap.add_argument("--keep-storage", action="store_true", help="跳过对象存储")
    ap.add_argument("--no-rebuild", action="store_true", help="清表后不自动执行 alembic upgrade head")
    args = ap.parse_args()

    print("=" * 64)
    print("一键清空数据环境" + ("（预览模式，不执行）" if args.dry_run else ""))
    print(f"  DB      : {settings.resolved_database_url}")
    print(f"  Milvus  : {settings.milvus_host}:{settings.milvus_port} / {settings.milvus_collection}")
    storage_label = (
        f"minio://{settings.minio_endpoint}/{settings.minio_bucket}"
        if settings.storage_backend.lower() == "minio"
        else f"local://{settings.upload_dir}"
    )
    print(f"  Storage : {settings.storage_backend} / {storage_label}")
    print("=" * 64)
    if not args.dry_run:
        print("⚠️  请确认后端服务已停止，否则运行中的请求会因表不存在而报错。")

    if not args.yes and not args.dry_run:
        if not _ask("确认清空以上全部数据？此操作不可恢复"):
            print("已取消")
            return 1

    db_tables: list[str] = []
    if not args.keep_db:
        print("\n[1/3] 清空 MySQL 业务表")
        db_tables = await reset_database(args.dry_run)
    else:
        print("\n[1/3] 跳过 MySQL")

    if not args.keep_milvus:
        print("\n[2/3] 清空 Milvus 向量集合")
        await reset_milvus(args.dry_run)
    else:
        print("\n[2/3] 跳过 Milvus")

    if not args.keep_storage:
        print("\n[3/3] 清空对象存储")
        await reset_storage(args.dry_run)
    else:
        print("\n[3/3] 跳过对象存储")

    # 清表后自动重建结构（默认开启；--no-rebuild 跳过，由用户手动执行 alembic upgrade head）
    if not args.keep_db and db_tables and not args.dry_run and not args.no_rebuild:
        print("\n[重建] 重建数据库表结构")
        try:
            rebuild_schema()
        except subprocess.CalledProcessError as exc:
            print(f"  [DB] alembic upgrade head 失败（{exc}），请手动执行：")
            print("       cd backend && .\\.venv\\Scripts\\python.exe -m alembic upgrade head")
            return 2

    print("\n完成。")
    print("提示：")
    print("  - 数据库表已重建（alembic upgrade head）；启动后端会自动创建默认 admin/admin 与默认知识库")
    print("  - Milvus 集合已重建为空；上传文档时 ingestion 也会自动 ensure_collection")
    print("  - 对象存储已清空；bucket 不存在时后端启动自动创建")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
