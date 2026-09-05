"""文件存储抽象层：统一原始文档的读写删，屏蔽本地盘与 MinIO 差异。

设计：
- 接口为**同步**（本地文件与 minio SDK 都是阻塞 IO）。
  - async 的 service 层用 ``await asyncio.to_thread(storage.put, ...)`` 隔离事件循环；
  - CLI 脚本（scripts/）可直接同步调用，无需 asyncio 包装。
- key 为逻辑路径，统一用正斜杠，如 ``{kb_id}/{doc_id}/report.pdf``；
  具体目录结构由上层 document_service 决定，本层不解释 key 语义。
- 开发期 STORAGE_BACKEND=local 写 data/uploads；部署期切 minio，业务代码零改动。
"""

from __future__ import annotations

import io
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageError(Exception):
    """存储层统一异常。"""


class ObjectNotFoundError(StorageError):
    """读取的对象不存在。delete 对不存在的对象幂等，不抛此异常。"""


def _normalize_key(key: str) -> str:
    """校验并规范化 key：禁止绝对路径与 ``..`` 逃逸，统一正斜杠。"""
    if not key:
        raise StorageError("key 不能为空")
    p = PurePosixPath(key.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        raise StorageError(f"非法 key（禁止绝对路径或 .. 逃逸）: {key!r}")
    return p.as_posix()


class FileStorage(ABC):
    """文件存储统一接口。所有实现均为同步阻塞实现。"""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """写入/覆盖一个对象。"""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """读取对象全部内容；不存在抛 ObjectNotFoundError。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除对象；对象不存在时静默返回（幂等）。"""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """对象是否存在。"""

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """按前缀列出对象 key（递归）。"""


class LocalStorage(FileStorage):
    """本地盘实现：root 为 settings.upload_dir。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.upload_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorage 根目录: %s", self.root)

    def _resolve(self, key: str) -> Path:
        key = _normalize_key(key)
        target = (self.root / key).resolve()
        # 防路径穿越：规范化后必须仍在 root 内
        if self.root not in target.parents and target != self.root:
            raise StorageError(f"非法 key（越出存储根目录）: {key!r}")
        return target

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise ObjectNotFoundError(f"对象不存在: {key}")
        return target.read_bytes()

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            target.unlink()
            # 清理空的父目录（不删 root）
            parent = target.parent
            while parent != self.root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def list_keys(self, prefix: str = "") -> list[str]:
        prefix = prefix.replace("\\", "/")
        result: list[str] = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if not prefix or rel.startswith(prefix):
                result.append(rel)
        return sorted(result)


class MinioStorage(FileStorage):
    """MinIO 对象存储实现。复用 docker-compose 中已运行的 MinIO 实例。"""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        from minio import Minio
        from minio.error import S3Error  # noqa: F401  确保依赖可导入，便于早期报错

        self.bucket = bucket or settings.minio_bucket
        self._S3Error = S3Error
        self.client = Minio(
            endpoint or settings.minio_endpoint,
            access_key=access_key or settings.minio_access_key,
            secret_key=secret_key or settings.minio_secret_key,
            secure=settings.minio_secure if secure is None else secure,
        )
        self._ensure_bucket()
        logger.info("MinioStorage: endpoint=%s bucket=%s", settings.minio_endpoint, self.bucket)

    def _ensure_bucket(self) -> None:
        """业务 bucket 不存在则创建（MinIO 不会自动建）。"""
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info("已创建 MinIO bucket: %s", self.bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        key = _normalize_key(key)
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get(self, key: str) -> bytes:
        key = _normalize_key(key)
        try:
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except self._S3Error as e:
            if e.code == "NoSuchKey":
                raise ObjectNotFoundError(f"对象不存在: {key}") from e
            raise StorageError(f"读取对象失败 {key}: {e}") from e

    def delete(self, key: str) -> None:
        key = _normalize_key(key)
        # remove_object 对不存在的 key 也不报错，天然幂等
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        key = _normalize_key(key)
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except self._S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise StorageError(f"查询对象失败 {key}: {e}") from e

    def list_keys(self, prefix: str = "") -> list[str]:
        return sorted(
            obj.object_name
            for obj in self.client.list_objects(
                self.bucket, prefix=prefix or None, recursive=True
            )
            if obj.object_name
        )


_storage: FileStorage | None = None


def get_storage() -> FileStorage:
    """按 settings.storage_backend 返回进程内单例存储实例。"""
    global _storage
    if _storage is None:
        backend = settings.storage_backend.lower()
        if backend == "minio":
            _storage = MinioStorage()
        elif backend == "local":
            _storage = LocalStorage()
        else:
            raise StorageError(f"未知 storage_backend: {backend!r}（支持 local / minio）")
    return _storage


def reset_storage() -> None:
    """重置单例（测试或切换后端时使用）。"""
    global _storage
    _storage = None
