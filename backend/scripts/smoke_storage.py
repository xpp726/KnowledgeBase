"""文件存储层冒烟：验证 Local / MinIO 两实现的 put/get/exists/list/delete 全流程。

用法：
    python scripts/smoke_storage.py            # 两个后端都测（MinIO 不可达则跳过并报告）
    python scripts/smoke_storage.py local      # 只测本地盘
    python scripts/smoke_storage.py minio      # 只测 MinIO
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.storage import (  # noqa: E402
    LocalStorage,
    MinioStorage,
    ObjectNotFoundError,
    StorageError,
)

PAYLOAD = b"knowledge-base storage smoke test \x00\x01\x02 \xe4\xb8\xad\xe6\x96\x87"
KEY = "smoke/kb01/doc01/sample.bin"


def _exercise(name: str, store) -> bool:
    """对任一实现跑完整读写删流程，全部通过返回 True。"""
    print(f"\n=== {name} ===")
    try:
        # 清理可能的残留
        store.delete(KEY)

        print("  [1] exists(初始) =", store.exists(KEY))
        assert store.exists(KEY) is False, "初始不应存在"

        store.put(KEY, PAYLOAD, content_type="application/octet-stream")
        print("  [2] put 完成, exists =", store.exists(KEY))
        assert store.exists(KEY) is True

        got = store.get(KEY)
        assert got == PAYLOAD, f"读回内容不一致，长度 {len(got)} != {len(PAYLOAD)}"
        print(f"  [3] get 读回 {len(got)} 字节，内容一致 OK")

        keys = store.list_keys("smoke/")
        assert KEY in keys, f"list 未包含 {KEY}: {keys}"
        print(f"  [4] list('smoke/') = {keys}")

        # 覆盖写
        store.put(KEY, b"overwrite")
        assert store.get(KEY) == b"overwrite", "覆盖写失败"
        store.put(KEY, PAYLOAD)  # 还原
        print("  [5] 覆盖写 OK")

        # 幂等删除
        store.delete(KEY)
        assert store.exists(KEY) is False, "删除后仍存在"
        store.delete(KEY)  # 再删一次不应抛
        print("  [6] delete + 幂等再删 OK")

        # get 不存在应抛 ObjectNotFoundError
        try:
            store.get(KEY)
            raise AssertionError("get 不存在的对象应抛 ObjectNotFoundError")
        except ObjectNotFoundError:
            print("  [7] get 不存在 → ObjectNotFoundError OK")

        # 路径穿越防护
        for bad in ["../escape.bin", "/abs.bin", "a/../../b.bin"]:
            try:
                store.put(bad, b"x")
                raise AssertionError(f"非法 key 未被拦截: {bad}")
            except StorageError:
                pass
        print("  [8] 路径穿越拦截 OK（../ 与绝对路径）")

        print(f"  [PASS] {name} 全部通过")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
        return False


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    results: dict[str, bool] = {}

    if target in ("local", "both"):
        # 用临时目录，避免污染 data/uploads
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            results["local"] = _exercise("LocalStorage", LocalStorage(root=Path(tmp)))

    if target in ("minio", "both"):
        try:
            results["minio"] = _exercise("MinioStorage", MinioStorage())
        except Exception as e:  # noqa: BLE001  MinIO 不可达不算脚本崩溃
            print(f"\n=== MinioStorage ===\n  [SKIP] MinIO 不可达: {type(e).__name__}: {e}")
            results["minio"] = None  # type: ignore[assignment]

    print("\n" + "=" * 50)
    for name, ok in results.items():
        status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        print(f"  {name}: {status}")
    failed = [n for n, ok in results.items() if ok is False]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
