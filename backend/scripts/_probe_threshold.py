"""相似度阈值标定工具：对比“已知相关 / 明确无关”问题的 dense 分数分布，辅助确定 SCORE_THRESHOLD。

用法（需已 ingest 入库、Embedding/Milvus 在线）：
    python scripts/_probe_threshold.py

输出相关问题 top1 下界与无关问题 top1 上界，阈值应落在两者之间并偏上沿（更防幻觉）。
语料大幅扩充后，分数分布会漂移，应补充本文件内的 QUESTIONS/UNRELATED 后重新标定，
再更新 app/config.py 的 score_threshold 默认值或用 .env 的 SCORE_THRESHOLD 覆盖。
"""
import asyncio
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from scripts.eval_retrieval import QUESTIONS  # noqa: E402
from app.services.embedding import get_embedder  # noqa: E402
from app.services.vectorstore import get_vectorstore  # noqa: E402

UNRELATED = [
    "请详细推导量子力学里薛定谔方程的数学过程",
    "红烧肉的家常做法是什么",
    "NBA 本赛季常规赛赛程安排",
    "如何维修汽车发动机的点火系统",
    "介绍一下法国大革命的历史背景",
    "帮我写一首关于月亮的七言绝句",
]


async def scores(embedder, store, q):
    d, _ = await embedder.embed_query(q)
    hits = store.dense_search(d, top_k=5)
    return [round(h.score, 4) for h in hits]


async def main():
    emb = get_embedder()
    store = get_vectorstore()
    store.load()
    print("== 已知相关问题（应保留）dense top1..top5 ==")
    related_top1 = []
    for item in QUESTIONS:
        s = await scores(emb, store, item["q"])
        related_top1.append(s[0])
        print(f"  {item['note']:<12} {s}")
    print(f"\n  相关问题 top1: min={min(related_top1):.4f} median={median(related_top1):.4f} max={max(related_top1):.4f}")

    print("\n== 明确无关问题（应判无命中）dense top1..top5 ==")
    unrelated_top1 = []
    for q in UNRELATED:
        s = await scores(emb, store, q)
        unrelated_top1.append(s[0])
        print(f"  {q[:22]:<24} {s}")
    print(f"\n  无关问题 top1: max={max(unrelated_top1):.4f} median={median(unrelated_top1):.4f}")
    print(f"\n== 分界建议：阈值取 相关min({min(related_top1):.3f}) 与 无关max({max(unrelated_top1):.3f}) 之间 ==")


asyncio.run(main())
