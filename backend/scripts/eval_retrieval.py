"""检索效果与质量验证。

用法：
    python scripts/eval_retrieval.py

指标：
- 命中率 Recall@K：返回的 K 条中是否包含"期望命中"
- 期望命中：用文件名包含的关键词（省份/项目编号）做软匹配
- 延迟分布：P50 / P95 / P99
- 路径对比：dense / sparse / hybrid（RRF）三路在每条问题上的命中率

跑前需要：先 ingest.py 把 8 篇样例文档入库完。
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db as db  # noqa: E402

async def db_stats() -> dict:
    """统计 DB 中的文档/分块数据（MySQL，替代已清理的 legacy sqlite db.stats）。"""
    from sqlalchemy import text

    from app.db import async_engine

    async with async_engine.connect() as conn:
        docs = (await conn.execute(text("SELECT COUNT(*) FROM documents"))).scalar()
        chunks = (await conn.execute(text("SELECT COUNT(*) FROM chunks"))).scalar()
        tables = (await conn.execute(text("SELECT COUNT(*) FROM chunks WHERE is_table = 1"))).scalar()
        chars = (await conn.execute(text("SELECT COALESCE(SUM(CHAR_LENGTH(text)),0) FROM chunks"))).scalar()
    return {"documents": docs, "chunks": chunks, "table_chunks": tables, "total_chars": chars}
from app.config import get_settings  # noqa: E402
from app.services.embedding import get_embedder  # noqa: E402
from app.services.vectorstore import get_vectorstore  # noqa: E402

logging.basicConfig(
    level=logging.WARNING, format="%(message)s"
)
logger = logging.getLogger("eval")
settings = get_settings()

# ---- 评测集：问题 + 期望命中关键词 ----
# 每条问题都对应到 1 篇或多篇样例文档，关键词是文档名里稳定出现的片段
QUESTIONS: list[dict] = [
    {
        "q": "国网江西电力 2026 年服务新增第一次公开招标采购推荐的中标候选人",
        "expect_any": ["182609"],
        "note": "江西公开招标",
    },
    {
        "q": "国网江西电力 2026 年服务新增第一次邀请谈判采购推荐的中标候选人",
        "expect_any": ["182610"],
        "note": "江西邀请谈判",
    },
    {
        "q": "国网江苏电力徐州供电公司 2026 年第四次服务授权公开谈判采购成交候选人",
        "expect_any": ["江苏电力徐州"],
        "note": "江苏徐州",
    },
    {
        "q": "国网江苏电力泰州供电公司 2026 年第四次服务授权公开谈判采购成交候选人",
        "expect_any": ["江苏电力泰州"],
        "note": "江苏泰州",
    },
    {
        "q": "国网河南电力 2026 年第一次主业授权联合批次竞争性谈判成交候选人及否决原因",
        "expect_any": ["联合批次"],
        "note": "河南否决原因",
    },
    {
        "q": "国网河南电力 2026 年第一次主业授权联合框架协议竞争性谈判成交候选人",
        "expect_any": ["联合框架"],
        "note": "河南框架协议",
    },
    {
        "q": "国网浙江电力宁波供电公司 2026 年第一次物资授权竞争性谈判磋商采购成交候选人",
        "expect_any": ["宁波"],
        "note": "浙江宁波",
    },
    {
        "q": "2026 年 7 月 8 日推荐的中标候选人公示",
        "expect_any": ["2026-07-08"],
        "note": "7-08 Excel",
    },
    # 跨文档检索：所有表格里都有的"投标报价"列
    {
        "q": "投标报价",
        "expect_any": ["182609", "182610", "江苏电力徐州", "江苏电力泰州",
                       "联合批次", "联合框架", "宁波", "2026-07-08"],
        "note": "通用表格列",
    },
    # 否定测试：只在一个文档里出现
    {
        "q": "否决原因公示",
        "expect_any": ["联合批次"],
        "note": "否定指向唯一",
    },
]


def hits_contain(doc_names: list[str], expect_any: list[str]) -> bool:
    """前 K 个命中里是否出现任一期望关键词。"""
    if not expect_any:
        return True
    for name in doc_names:
        if any(kw in name for kw in expect_any):
            return True
    return False


def first_hit_rank(doc_names: list[str], expect_any: list[str]) -> int:
    """期望命中出现的最小序号（1-based），0 表示未命中。"""
    for i, name in enumerate(doc_names, 1):
        if any(kw in name for kw in expect_any):
            return i
    return 0


async def eval_one_path(
    embedder, store, mode: str, question: str, expect_any: list[str], k: int
) -> dict:
    """单条问题单种检索路径的评估。"""
    res = await embedder.embed([question])

    t0 = time.perf_counter()
    if mode == "dense":
        hits = store.dense_search(res.dense[0], top_k=k)
    elif mode == "sparse":
        hits = store.sparse_search(res.sparse[0], top_k=k)
    else:  # hybrid
        hits = store.hybrid_search(
            dense=res.dense[0], sparse=res.sparse[0], top_k=k
        )
    dt_ms = (time.perf_counter() - t0) * 1000

    doc_names = [h.doc_name for h in hits]
    return {
        "mode": mode,
        "hits": doc_names,
        "recall": hits_contain(doc_names, expect_any),
        "rank": first_hit_rank(doc_names, expect_any),
        "latency_ms": dt_ms,
    }


async def main() -> int:
    embedder = get_embedder()
    store = get_vectorstore()
    store.load()

    # 让 BGE-M3 热起来
    await embedder.warmup()

    K = 5
    rows = []
    latencies: dict[str, list[float]] = {"dense": [], "sparse": [], "hybrid": []}

    print(f"\n{'='*72}")
    print(f"问题总数 {len(QUESTIONS)}    Top-K = {K}    检索模式 dense / sparse / hybrid(RRF)")
    print(f"{'='*72}\n")

    for qi, item in enumerate(QUESTIONS, 1):
        q = item["q"]
        expect = item["expect_any"]
        print(f"[Q{qi}] {item['note']}")
        print(f"      {q}")
        line = {}
        for mode in ("dense", "sparse", "hybrid"):
            r = await eval_one_path(embedder, store, mode, q, expect, K)
            line[mode] = r
            latencies[mode].append(r["latency_ms"])
            mark = "✓" if r["recall"] else "✗"
            rank = r["rank"] if r["rank"] else "-"
            print(
                f"      {mode:>6}: {mark} rank={rank:>2}  "
                f"{r['latency_ms']:>5.1f}ms  → {r['hits'][0][:40] if r['hits'] else '(空)'}"
            )
        rows.append({"q": q, "expect": expect, "note": item["note"], **line})
        print()

    # ---- 汇总 ----
    print("=" * 72)
    print("汇总")
    print("=" * 72)

    summary = {}
    for mode in ("dense", "sparse", "hybrid"):
        recall = sum(1 for r in rows if r[mode]["recall"]) / len(rows)
        ranks = [r[mode]["rank"] for r in rows if r[mode]["rank"]]
        mrr = (sum(1.0 / r for r in ranks) / len(rows)) if ranks else 0.0
        lats = sorted(latencies[mode])
        p50 = statistics.median(lats)
        p95 = lats[int(len(lats) * 0.95)] if len(lats) >= 2 else lats[-1]
        p99 = lats[int(len(lats) * 0.99)] if len(lats) >= 2 else lats[-1]
        summary[mode] = {
            "recall_at_5": recall,
            "mrr": mrr,
            "p50_ms": p50, "p95_ms": p95, "p99_ms": p99,
        }

    # 漂亮的表格
    print(f"\n{'指标':<14}{'dense':>14}{'sparse':>14}{'hybrid':>14}")
    print("-" * 56)
    for label, key in [("Recall@5", "recall_at_5"), ("MRR", "mrr")]:
        print(
            f"{label:<14}"
            f"{summary['dense'][key]*100:>12.1f}%"
            f"{summary['sparse'][key]*100:>12.1f}%"
            f"{summary['hybrid'][key]*100:>12.1f}%"
        )
    for label, key in [("P50 (ms)", "p50_ms"), ("P95 (ms)", "p95_ms"), ("P99 (ms)", "p99_ms")]:
        print(
            f"{label:<14}"
            f"{summary['dense'][key]:>14.1f}"
            f"{summary['sparse'][key]:>14.1f}"
            f"{summary['hybrid'][key]:>14.1f}"
        )

    # ---- 每条问题的命中矩阵 ----
    print(f"\n{'问题':<12}{'期望命中':<24}{'dense':>8}{'sparse':>8}{'hybrid':>8}")
    print("-" * 60)
    for r in rows:
        d = r["dense"]["rank"] or "-"
        s = r["sparse"]["rank"] or "-"
        h = r["hybrid"]["rank"] or "-"
        print(f"{r['note']:<12}{str(r['expect'])[:22]:<24}{str(d):>8}{str(s):>8}{str(h):>8}")

    # ---- 出报告 ----
    out = {
        "settings": {
            "top_k": K,
            "questions": len(QUESTIONS),
            "kb_total": store.count(),
            "kb_chunks": await db_stats(),
        },
        "summary": summary,
        "rows": [
            {
                "note": r["note"], "q": r["q"],
                "dense_rank": r["dense"]["rank"],
                "sparse_rank": r["sparse"]["rank"],
                "hybrid_rank": r["hybrid"]["rank"],
                "hybrid_top_doc": r["hybrid"]["hits"][0] if r["hybrid"]["hits"] else "",
            }
            for r in rows
        ],
    }
    out_path = Path(settings.data_dir) / "retrieval_eval.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))