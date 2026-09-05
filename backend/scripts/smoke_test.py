"""阶段 0 冒烟测试：验证本机自建基础设施的连通性。

不依赖 FastAPI，直接用客户端打三个服务端点，
重点排查 pymilvus 3.x 客户端与 Milvus 2.5.x 服务端的兼容性。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402

settings = get_settings()


def check_milvus() -> None:
    print("=== Milvus ===")
    print(f"  目标: {settings.milvus_host}:{settings.milvus_port}")
    import pymilvus

    print(f"  pymilvus 版本: {pymilvus.__version__}")
    from pymilvus import connections, utility

    t0 = time.perf_counter()
    connections.connect(
        alias="smoke",
        host=settings.milvus_host,
        port=settings.milvus_port,
        timeout=20.0,
    )
    try:
        version = utility.get_server_version(using="smoke")
        collections = utility.list_collections(using="smoke")
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  [OK] 服务端版本: {version}")
        print(f"  [OK] 集合列表: {collections}")
        print(f"  [OK] 目标集合 {settings.milvus_collection} 存在: "
              f"{settings.milvus_collection in collections}")
        print(f"  耗时: {elapsed:.0f} ms")
    finally:
        connections.disconnect("smoke")


def check_embedding() -> None:
    print("\n=== BGE-M3 ===")
    print(f"  目标: {settings.embed_base_url}")
    import httpx

    t0 = time.perf_counter()
    r = httpx.post(
        f"{settings.embed_base_url}/embed",
        json={
            "texts": ["联通性验证", "国网江苏电力徐州供电公司成交候选人公示"],
            "return_dense": True,
            "return_sparse": True,
        },
        timeout=180.0,
    )
    r.raise_for_status()
    data = r.json()
    dense = data.get("dense_vectors") or []
    sparse = data.get("sparse_vectors") or []
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  [OK] dense 维度: {len(dense[0]) if dense else 0}")
    print(f"  [OK] sparse 非零项: {len(sparse[0]) if sparse else 0}")
    print(f"  耗时: {elapsed:.0f} ms")


async def _probe_llm() -> None:
    from app.services.llm import get_llm

    print(f"  provider: {settings.llm_provider}")
    provider = get_llm()
    print(f"  model: {provider.model}  base_url: {provider.base_url}")
    t0 = time.perf_counter()
    reply = await provider.chat(
        [{"role": "user", "content": "只回复两个字：正常"}], max_tokens=16
    )
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  [OK] 回复: {reply[:60]!r}")
    print(f"  耗时: {elapsed:.0f} ms")


def check_llm() -> None:
    """LLM 探测（provider.chat 是异步方法，必须用 asyncio 驱动）。"""
    print("\n=== LLM ===")
    import asyncio

    asyncio.run(_probe_llm())


if __name__ == "__main__":
    failed = []
    for name, fn in (
        ("milvus", check_milvus),
        ("embedding", check_embedding),
        ("llm", check_llm),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"  [FAIL] {type(e).__name__}: {e}")
    print("\n" + "=" * 40)
    print("失败项:", failed or "无")
    sys.exit(1 if failed else 0)
