"""文件夹模型（kb 维度的树状组织单位）。

层级约束：
- depth=1：顶层 folder（直接挂在 kb 下，包括系统自动建的"默认 folder"）
- depth=2：子 folder（挂在顶层 folder 下）
- 文件落在 depth=2 folder 下；文件不能再嵌套
- 最多 3 层（kb → 顶层 → 子 → 文件）由 service 层在创建时强制

唯一性：
- (kb_id, parent_id, name) 联合唯一 → 同 parent 下 folder 名唯一，不同层级可同名
- 文件同名唯一由 service 层在 upload 时校验

系统保护：
- is_system=True 的 folder（默认 folder）允许重命名，**禁止删除**
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Folder(Base, TimestampMixin):
    __tablename__ = "folders"

    folder_id: Mapped[str] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(default="default", index=True)
    # 顶层 folder 的 parent_id 为 NULL；子 folder 指向顶层 folder_id
    parent_id: Mapped[str | None] = mapped_column(default=None, index=True)
    name: Mapped[str] = mapped_column(default="")
    # 1 = 顶层（kb 下），2 = 子 folder（深度上限）
    depth: Mapped[int] = mapped_column(default=1)
    # 系统 folder（默认 folder）标记：禁止删除，允许重命名
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        # 同 parent 下 name 唯一（kb 顶层时 parent_id IS NULL 也独立一组）
        Index(
            "uq_folders_kb_parent_name",
            "kb_id", "parent_id", "name",
            unique=True,
        ),
    )