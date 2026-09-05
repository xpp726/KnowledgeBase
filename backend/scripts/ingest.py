"""批量入库 CLI（薄壳）：参数解析 + 收集文件，业务流水线统一走 services.ingestion。

用法：
    python scripts/ingest.py                     # 入库 test_files/ 到默认知识库
    python scripts/ingest.py <路径>               # 入库指定目录或文件
    python scripts/ingest.py --recreate          # 重建 Milvus 集合后全量入库
    python scripts/ingest.py --force             # 忽略 done 状态，强制重跑
    python scripts/ingest.py --kb kb2            # 入库到指定知识库

Web 上传与本脚本共用 services.ingestion.ingest_bytes，不存在两套流水线。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db as db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.embedding import get_embedder  # noqa: E402
from app.services.ingestion import ingest_path  # noqa: E402
from app.db import get_async_session  # noqa: E402
from app.models import queries  # noqa: E402
from app.services.parsers import supported_extensions  # noqa: E402
from app.services.storage import get_storage  # noqa: E402
from app.services.vectorstore import get_vectorstore  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger("ingest")
settings = get_settings()

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "test_files"


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    exts = set(supported_extensions())
    return sorted(p for p in target.iterdir() if p.suffix.lower() in exts)


async def main() -> int:
    ap = argparse.ArgumentParser(description="知识库批量入库")
    ap.add_argument("target", nargs="?", default=str(DEFAULT_DIR), help="目录或文件")
    ap.add_argument("--recreate", action="store_true", help="删除并重建 Milvus 集合")
    ap.add_argument("--force", action="store_true", help="忽略已完成状态，强制重跑")
    ap.add_argument("--no-warmup", action="store_true", help="跳过 BGE-M3 预热")
    ap.add_argument("--kb", default=settings.default_kb_id, help="目标知识库 id")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        logger.error("路径不存在: %s", target)
        return 1

    # 开发期便捷建表（IF NOT EXISTS）；生产用 alembic upgrade head
    await db.create_all()

    store = get_vectorstore()
    embedder = get_embedder()
    storage = get_storage()

    # Milvus 集合（schema 含 kb_id），--recreate 时 drop 重建
    store.ensure_collection(drop_if_exists=args.recreate)
    store.load()

    files = collect_files(target)
    if not files:
        logger.error("未找到支持的文件（%s）", supported_extensions())
        return 1
    logger.info("待入库 %d 个文件 → 知识库 %s，存储后端 %s",
                len(files), args.kb, settings.storage_backend)

    if not args.no_warmup:
        await embedder.warmup()

    t0 = time.perf_counter()
    results = []
    for path in files:
        r = await ingest_path(
            path,
            kb_id=args.kb,
            embedder=embedder,
            store=store,
            storage=storage,
            force=args.force,
        )
        results.append(r)

    store.load()
    total = time.perf_counter() - t0

    done = [r for r in results if r.status == "done"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]

    async with get_async_session() as session:
        db_stats = await queries.stats(session)

    print("\n" + "=" * 60)
    print(f"成功 {len(done)}  失败 {len(failed)}  跳过 {len(skipped)}")
    print(f"chunk 总数 {sum(r.chunks for r in done)}"
          f"（表格块 {sum(r.table_chunks for r in done)}）")
    print(f"Milvus 集合 {store.collection} 现有 {store.count()} 条")
    print(f"DB 统计: {db_stats}")
    print(f"总耗时 {total:.1f}s")
    if failed:
        print("\n失败文件:")
        for r in failed:
            print(f"  - {r.file_name}: {r.error[:100]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
