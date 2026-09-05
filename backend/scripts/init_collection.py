"""向量库自检：建集合 → 写 3 条真实文本 → 混合检索验证。

这一步验证的是 schema 定义、双路索引、RRF 融合是否真的能在
Milvus v2.5.27 + pymilvus 3.0.1 组合下跑通，属于阶段 1 的地基。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.embedding import get_embedder  # noqa: E402
from app.services.vectorstore import get_vectorstore  # noqa: E402

SAMPLES = [
    "国网江西电力2026年服务新增第一次公开招标采购，推荐的中标候选人为江苏鑫顺能源产业集团有限公司，投标报价 128.6 万元。",
    "国网河南电力2026年第一次主业授权联合批次竞争性谈判，否决投标原因：未提供安全生产许可证。",
    "知识库系统采用 BGE-M3 模型同时输出 dense 与 sparse 向量，省去 Elasticsearch。",
]

QUERIES = [
    "江西电力招标的中标候选人是谁？报价多少？",
    "哪些投标被否决了，原因是什么",
]


async def main() -> int:
    embedder = get_embedder()
    store = get_vectorstore()

    print("=== 1. 建集合 ===")
    store.ensure_collection(drop_if_exists=True)
    print(f"  集合 {store.collection} 就绪")

    print("\n=== 2. 向量化并写入 ===")
    warm = await embedder.warmup()
    print(f"  预热耗时 {warm:.1f}s（首次含模型加载）")

    t0 = time.perf_counter()
    res = await embedder.embed(SAMPLES)
    print(f"  向量化 {len(res)} 条，耗时 {time.perf_counter() - t0:.2f}s")
    print(f"  dense 维度 {len(res.dense[0])}，sparse 非零项 {len(res.sparse[0])}")

    rows = [
        {
            "chunk_id": f"test-{i}",
            "doc_id": "doc-test",
            "doc_name": "自检样本文档",
            "text": text,
            "page": 1,
            "dense": res.dense[i],
            "sparse": res.sparse[i],
        }
        for i, text in enumerate(SAMPLES)
    ]
    n = store.insert(rows)
    store.load()
    print(f"  写入 {n} 条，集合总数 {store.count()}")

    print("\n=== 3. 混合检索验证 ===")
    for q in QUERIES:
        dense, sparse = await embedder.embed_query(q)
        t0 = time.perf_counter()
        hits = store.hybrid_search(dense, sparse, top_k=3)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  问：{q}")
        print(f"  混合检索 {len(hits)} 条，耗时 {elapsed:.0f} ms")
        for h in hits:
            print(f"    [{h.score:.4f}] {h.text[:52]}...")

    print("\n=== 4. 单路对比（首问）===")
    dense, sparse = await embedder.embed_query(QUERIES[0])
    for name, fn in (
        ("仅 dense", lambda: store.dense_search(dense, top_k=3)),
        ("仅 sparse", lambda: store.sparse_search(sparse, top_k=3)),
        ("混合 RRF", lambda: store.hybrid_search(dense, sparse, top_k=3)),
    ):
        t0 = time.perf_counter()
        hits = fn()
        elapsed = (time.perf_counter() - t0) * 1000
        top = hits[0].text[:34] if hits else "<无结果>"
        print(f"  {name:10s} {elapsed:5.0f} ms  首条: {top}...")

    print("\n[OK] 向量库自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
