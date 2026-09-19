"""原始文件存储端口。

端口只描述业务编排需要的能力，不暴露 MinIO、文件系统等具体 SDK。
实现保持同步，由 Application 层在异步流程中通过 ``asyncio.to_thread`` 调用。
"""

from __future__ import annotations

from typing import Protocol


class StorageError(Exception):
    """存储层统一异常。"""


class ObjectNotFoundError(StorageError):
    """读取的对象不存在。删除不存在的对象应保持幂等。"""


class FileStorage(Protocol):
    """文件存储的最小业务端口。"""

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...
