"""删除补偿兜底 / 一致性对账 CLI（步骤6）。

用法：
    python scripts/cleanup.py                      # 只读对账：DB ↔ Milvus ↔ 对象存储
    python scripts/cleanup.py --doc <doc_id>       # 对单个文档重跑删除补偿（幂等，可重复执行）
    python scripts/cleanup.py --recover-stuck      # 主动把卡死文档标记 failed
    python scripts/cleanup.py --purge-orphans      # 对账并删除“向量/文件有、DB 无”的孤儿（谨慎）

删除补偿定序见 app/services/document_service.delete_document：向量 → 文件 → DB，
DB 记录是账本最后删，因此任何一步中断后，重跑 --doc 都能安全续上，不会重复报错。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.db import get_async_session  # noqa: E402
from app.models import queries  # noqa: E402
from app.services import document_service  # noqa: E402
from app.services.storage import get_storage  # noqa: E402
from app.services.vectorstore import FIELD_DOC_ID, get_vectorstore  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("cleanup")


def _doc_id_from_key(key: str) -> str:
    parts = key.split("/")
    return parts[1] if len(parts) >= 2 else ""


async def vector_doc_ids(store) -> dict[str, int]:
    """Milvus 中每个 doc_id 的向量条数。"""
    store.load()
    rows = store.client.query(
        collection_name=store.collection,
        filter="",
        output_fields=[FIELD_DOC_ID],
        limit=16384,
    )
    counts: dict[str, int] = {}
    for r in rows:
        did = r.get(FIELD_DOC_ID, "")
        counts[did] = counts.get(did, 0) + 1
    return counts


async def db_snapshot() -> dict[str, dict]:
    async with get_async_session() as session:
        docs = await queries.list_documents(session)
        return {
            d.doc_id: {"status": d.status, "file_path": d.file_path, "kb_id": d.kb_id}
            for d in docs
        }


def storage_doc_keys(storage) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for key in storage.list_keys():
        did = _doc_id_from_key(key)
        if did:
            grouped.setdefault(did, []).append(key)
    return grouped


async def check_orphans(purge: bool = False) -> int:
    store = get_vectorstore()
    storage = get_storage()
    db = await db_snapshot()
    vec = await vector_doc_ids(store)
    files = storage_doc_keys(storage)

    orphan_vec = {d: n for d, n in vec.items() if d not in db}
    orphan_files = {d: ks for d, ks in files.items() if d not in db}
    # DB 标记 done 但向量缺失（索引不完整，应重入库而非删除）
    missing_vec = {
        d: meta for d, meta in db.items()
        if meta["status"] == "done" and vec.get(d, 0) == 0
    }

    print("=" * 64)
    print(f"DB 文档 {len(db)} | Milvus doc_id {len(vec)} | 存储 doc 目录 {len(files)}")
    print("-" * 64)
    print(f"孤儿向量（向量有 / DB 无）{len(orphan_vec)} 个：")
    for d, n in orphan_vec.items():
        print(f"  - {d}: {n} 条向量")
    print(f"孤儿文件（文件有 / DB 无）{len(orphan_files)} 个：")
    for d, ks in orphan_files.items():
        for k in ks:
            print(f"  - {k}")
    print(f"缺向量（DB=done 但 Milvus 无）{len(missing_vec)} 个：")
    for d, meta in missing_vec.items():
        print(f"  - {d}（{meta['status']}，建议 reprocess 重入库）")

    if purge:
        print("-" * 64)
        for d, n in orphan_vec.items():
            store.delete_by_doc(d)
            print(f"  已清孤儿向量 {d}（{n} 条）")
        for d, ks in orphan_files.items():
            for k in ks:
                storage.delete(k)
                print(f"  已清孤儿文件 {k}")
    elif orphan_vec or orphan_files or missing_vec:
        print("\n仅报告未删除；确认后加 --purge-orphans 清理孤儿向量/文件（缺向量请重入库）。")
    print("=" * 64)
    return 0


async def amain(args) -> int:
    if args.doc:
        report = await document_service.delete_document(args.doc)
        print(report.to_dict())
        return 0 if report.ok else 2
    if args.recover_stuck:
        ids = await document_service.recover_stuck()
        print(f"恢复卡死文档 {len(ids)} 个：{ids}")
        return 0
    return await check_orphans(purge=args.purge_orphans)


def main() -> int:
    ap = argparse.ArgumentParser(description="删除补偿兜底 / 一致性对账")
    ap.add_argument("--doc", help="对指定 doc_id 重跑删除补偿")
    ap.add_argument("--recover-stuck", action="store_true", help="把卡死文档标记 failed")
    ap.add_argument("--purge-orphans", action="store_true", help="对账后删除孤儿向量/文件")
    return asyncio.run(amain(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
