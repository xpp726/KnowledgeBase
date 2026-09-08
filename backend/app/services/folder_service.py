"""Folder service：kb 内的树状组织 CRUD + 树构建 + 级联删除。

设计要点（与 docs/MEMORY 同步）：
- 树根：kb 顶级；folder 隶属于 kb。
- 嵌套深度：最多 3 层（kb → 顶层 folder → 子 folder），文件落在子 folder。
- 同 parent 下 name 唯一；同名拒绝（不静默覆盖）。
- 系统默认 folder（is_system=True）禁止删除，允许重命名。
- 级联删除：BFS 取所有子孙 folder → 对每个 doc 走完整删除补偿 → 删 folder 记录。
- 不参与 RAG 检索：folder 是纯 UI 组织。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from app.db import get_async_session
from app.models import queries
from app.models.folder import Folder
from app.services import document_service as doc_svc

logger = logging.getLogger(__name__)

MAX_DEPTH = 2  # folder 最多 2 层（depth=1 顶层，depth=2 子 folder；文件落在 depth=2 下）
NAME_MAX_LEN = 64


# ==================== 异常 ====================

class FolderError(Exception):
    """folder service 业务异常基类。"""


class FolderNotFoundError(FolderError):
    """folder 不存在。"""


class FolderNameConflictError(FolderError):
    """同 parent 下 folder 名重复。"""

    def __init__(self, name: str, parent_id: str | None) -> None:
        super().__init__(f"同目录下已存在同名文件夹：{name}")
        self.name = name
        self.parent_id = parent_id


class FileNameConflictError(FolderError):
    """folder 内 file_name 重复：用户决策"同名拒绝"。"""

    def __init__(self, message: str = "同目录下已存在同名文件，请重命名后重传或删除原文件") -> None:
        super().__init__(message)


class FolderDepthLimitError(FolderError):
    """folder 嵌套超过 2 层（kb / 顶层 folder / 子 folder）。"""

    def __init__(self, max_depth: int = MAX_DEPTH) -> None:
        super().__init__(f"文件夹嵌套最多 {max_depth} 层")
        self.max_depth = max_depth


class FolderSystemProtectedError(FolderError):
    """默认 folder（is_system=True）不允许删除。"""


class FolderKbMismatchError(FolderError):
    """folder 跨 kb 操作（移动 / 创建等）。"""

    def __init__(self, expected_kb: str, got_kb: str) -> None:
        super().__init__(f"folder 跨 kb 操作：期望 {expected_kb}，实际 {got_kb}")
        self.expected_kb = expected_kb
        self.got_kb = got_kb


# ==================== 数据结构 ====================

@dataclass
class FolderNode:
    """folder 树节点（service 层返回给 API；序列化交给 pydantic）。"""

    folder_id: str
    kb_id: str
    parent_id: str | None
    name: str
    depth: int
    is_system: bool
    created_at: float
    updated_at: float
    doc_count: int = 0  # 直属（不含子 folder）的文件数
    children: list["FolderNode"] = field(default_factory=list)

    def total_doc_count(self) -> int:
        """递归计算本节点及所有子孙的文件总数。"""
        return self.doc_count + sum(c.total_doc_count() for c in self.children)


@dataclass
class DeleteFolderReport:
    """级联删除报告：folder + 子 folder + 文件 + 错误。"""

    folder_id: str
    folder_name: str = ""
    cascaded_folder_ids: list[str] = field(default_factory=list)
    deleted_doc_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ==================== 校验辅助 ====================

def _validate_name(name: str) -> str:
    """name 校验：去首尾空白、长度截断、禁止路径分隔符。"""
    name = (name or "").strip()
    if not name:
        raise FolderError("文件夹名不能为空")
    if len(name) > NAME_MAX_LEN:
        raise FolderError(f"文件夹名长度超过 {NAME_MAX_LEN}")
    # 路径分隔符会让前端面包屑 / 文件名展示混乱
    if "/" in name or "\\" in name:
        raise FolderError("文件夹名不能包含 / 或 \\")
    if name in {".", ".."}:
        raise FolderError("文件夹名不能为 . 或 ..")
    return name


def _folder_dict(f: Folder) -> dict:
    return {
        "folder_id": f.folder_id,
        "kb_id": f.kb_id,
        "parent_id": f.parent_id,
        "name": f.name,
        "depth": f.depth,
        "is_system": bool(f.is_system),
        "created_at": f.created_at,
        "updated_at": f.updated_at,
    }


def _folder_to_node(f: Folder, doc_count: int = 0) -> FolderNode:
    return FolderNode(
        folder_id=f.folder_id,
        kb_id=f.kb_id,
        parent_id=f.parent_id,
        name=f.name,
        depth=f.depth,
        is_system=bool(f.is_system),
        created_at=f.created_at,
        updated_at=f.updated_at,
        doc_count=doc_count,
    )


# ==================== 树构建 ====================

def build_tree(folders: list[Folder], doc_count_map: dict[str | None, int]) -> list[FolderNode]:
    """把扁平 folder 列表构建为嵌套树。doc_count_map 的 key 为 folder_id（None 统计无 folder 文件）。"""
    nodes: dict[str, FolderNode] = {}
    for f in folders:
        nodes[f.folder_id] = _folder_to_node(f, doc_count_map.get(f.folder_id, 0))

    roots: list[FolderNode] = []
    for f in folders:
        node = nodes[f.folder_id]
        if f.parent_id and f.parent_id in nodes:
            nodes[f.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


def build_folder_path(
    folder_id: str | None, folder_cache: dict[str, FolderNode]
) -> str:
    """把 folder_id 还原为完整路径字符串（面包屑 / 溯源展示）。

    路径按"祖先 → 子孙"顺序，以" / "分隔。
    folder_id 为 None 或找不到时返回空字符串。
    """
    if not folder_id or folder_id not in folder_cache:
        return ""
    chain: list[str] = []
    cur: str | None = folder_id
    visited: set[str] = set()
    while cur and cur in folder_cache and cur not in visited:
        visited.add(cur)
        chain.append(folder_cache[cur].name)
        cur = folder_cache[cur].parent_id
    return " / ".join(reversed(chain))


# ==================== CRUD ====================

async def ensure_default_for_kb(kb_id: str, name: str = "默认文件夹") -> dict:
    """某 kb 的默认 folder（无则建）。kb 创建时/启动时调用，幂等。"""
    async with get_async_session() as session:
        f = await queries.ensure_default_folder(session, kb_id, name=name)
        return _folder_dict(f)


async def create_folder(
    *, kb_id: str, parent_id: str | None, name: str
) -> dict:
    """新建 folder。

    - parent_id=None → 顶层 folder（depth=1）
    - parent_id 非空 → 子 folder（depth=parent.depth+1）；depth > MAX_DEPTH 拒绝
    - 同 parent 下 name 重复 → FolderNameConflictError
    - parent 不属于 kb → FolderKbMismatchError
    - kb 不存在 → 自动 ensure_knowledge_base
    """
    name = _validate_name(name)
    async with get_async_session() as session:
        # 确保 kb 存在（前端可能传错 kb_id）
        await queries.ensure_knowledge_base(session, kb_id, name=kb_id)

        # 计算 depth 与校验
        if parent_id is None:
            depth = 1
        else:
            parent = await queries.get_folder(session, parent_id)
            if parent is None:
                raise FolderNotFoundError(f"父文件夹不存在：{parent_id}")
            if parent.kb_id != kb_id:
                raise FolderKbMismatchError(kb_id, parent.kb_id)
            depth = parent.depth + 1
            if depth > MAX_DEPTH:
                raise FolderDepthLimitError()

        # 同名校验
        existed = await queries.find_folder_by_sibling_name(session, kb_id, parent_id, name)
        if existed is not None:
            raise FolderNameConflictError(name, parent_id)

        f = await queries.create_folder(
            session, kb_id=kb_id, parent_id=parent_id, depth=depth, name=name
        )
        logger.info("folder 已创建：%s (kb=%s parent=%s depth=%d)", f.name, kb_id, parent_id, depth)
        return _folder_dict(f)


async def rename_folder(folder_id: str, new_name: str) -> dict:
    """重命名 folder。同 parent 下同名拒绝（系统默认 folder 也允许改名）。"""
    new_name = _validate_name(new_name)
    async with get_async_session() as session:
        f = await queries.get_folder(session, folder_id)
        if f is None:
            raise FolderNotFoundError(folder_id)
        # 同名校验（除自身外）
        conflict = await queries.find_folder_by_sibling_name(
            session, f.kb_id, f.parent_id, new_name
        )
        if conflict is not None and conflict.folder_id != folder_id:
            raise FolderNameConflictError(new_name, f.parent_id)
        await queries.rename_folder(session, f, new_name)
        logger.info("folder 已重命名：%s → %s", folder_id, new_name)
        return _folder_dict(f)


async def move_folder(folder_id: str, new_parent_id: str | None) -> dict:
    """拖拽移动：parent 必须同 kb；移入深度 ≤ MAX_DEPTH。

    - 系统默认 folder（is_system=True）禁止移动（保持 kb 顶层根特性）
    - 不允许移入自身或自身子孙（避免成环）
    """
    async with get_async_session() as session:
        f = await queries.get_folder(session, folder_id)
        if f is None:
            raise FolderNotFoundError(folder_id)
        if f.is_system:
            raise FolderSystemProtectedError(f"默认文件夹不允许移动：{f.name}")

        new_depth = 1
        if new_parent_id is not None:
            # 禁止移到自身或子孙
            if new_parent_id == folder_id:
                raise FolderError("不能将文件夹移到自身内")
            descendants = await queries.collect_descendant_folder_ids(session, [folder_id])
            if new_parent_id in descendants:
                raise FolderError("不能将文件夹移到自身子孙目录下")
            new_parent = await queries.get_folder(session, new_parent_id)
            if new_parent is None:
                raise FolderNotFoundError(f"目标父文件夹不存在：{new_parent_id}")
            if new_parent.kb_id != f.kb_id:
                raise FolderKbMismatchError(f.kb_id, new_parent.kb_id)
            new_depth = new_parent.depth + 1

        if new_depth > MAX_DEPTH:
            raise FolderDepthLimitError()

        await queries.move_folder(session, f, new_parent_id)
        # 移动后，本 folder + 所有子孙的 depth 都要重新计算
        await _propagate_depths(session, folder_id, new_depth)
        logger.info("folder 已移动：%s → parent=%s", folder_id, new_parent_id)
        # 重读最新值
        await session.refresh(f)
        return _folder_dict(f)


async def _propagate_depths(session, root_id: str, root_depth: int) -> None:
    """BFS 重算 root_id 下所有子孙的 depth（移动后用）。"""
    from sqlalchemy import select

    frontier = [(root_id, root_depth)]
    visited: set[str] = {root_id}
    while frontier:
        cur_id, cur_depth = frontier.pop(0)
        node = (
            await session.execute(select(Folder).where(Folder.folder_id == cur_id))
        ).scalars().first()
        if node is None:
            continue
        node.depth = cur_depth
        await session.flush()
        # 取直接子
        children_stmt = select(Folder.folder_id).where(Folder.parent_id == cur_id)
        for cid, in (await session.execute(children_stmt)).all():
            if cid not in visited:
                visited.add(cid)
                frontier.append((cid, cur_depth + 1))


async def get_folder_tree(kb_id: str) -> list[dict]:
    """某 kb 下的 folder 嵌套树（dict 形态，方便 pydantic FolderTreeNode 序列化）。"""
    async with get_async_session() as session:
        folders = await queries.list_folders_by_kb(session, kb_id)
        counts = await queries.count_documents_by_folder(session, kb_id)
        tree = build_tree(folders, counts)
        return [_node_to_dict(n) for n in tree]


def _node_to_dict(node: FolderNode) -> dict:
    return {
        "folder_id": node.folder_id,
        "kb_id": node.kb_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "depth": node.depth,
        "is_system": node.is_system,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "doc_count": node.doc_count,
        "children": [_node_to_dict(c) for c in node.children],
    }


async def get_folder_path_map(kb_id: str) -> dict[str, FolderNode]:
    """取某 kb 下所有 folder 的 name + parent_id，用于 document list 拼 folder_path。"""
    async with get_async_session() as session:
        folders = await queries.list_folders_by_kb(session, kb_id)
    return {f.folder_id: _folder_to_node(f, 0) for f in folders}


# ==================== 级联删除 ====================

async def delete_folder_cascade(folder_id: str) -> DeleteFolderReport:
    """级联删除 folder（含子孙 folder + 全部文件 + MinIO 存储 + 向量）。"""
    report = DeleteFolderReport(folder_id=folder_id)
    async with get_async_session() as session:
        f = await queries.get_folder(session, folder_id)
        if f is None:
            raise FolderNotFoundError(folder_id)
        if f.is_system:
            raise FolderSystemProtectedError(f"默认文件夹不允许删除：{f.name}")
        report.folder_name = f.name

        # BFS 取所有子孙 folder_id（含自身）
        all_folder_ids = await queries.collect_descendant_folder_ids(session, [folder_id])
        report.cascaded_folder_ids = all_folder_ids

        # 取所有要删除的 doc_id
        doc_ids = await queries.list_doc_ids_by_folders(session, all_folder_ids)
        report.deleted_doc_ids = doc_ids

    # 删每个 doc（走完整补偿：向量 → 文件 → DB）。这一步是异步的 IO 重活，
    # 不能在 session 里跑（避免连接占用过长）。逐个 try，错误累计到 report.errors。
    for doc_id in doc_ids:
        try:
            r = await doc_svc.delete_document(doc_id)
            if not r.ok:
                report.errors.append(f"{doc_id}: {';'.join(r.errors) or '未完全成功'}")
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"{doc_id}: {type(e).__name__}: {e}")

    # 删 folder 记录（先清 folder_id 外键引用，再删 folder；走 DELETE 模式避免外键阻塞）
    async with get_async_session() as session:
        # 防御：上一步失败的 doc 仍指向 folder；先把残留指向 NULL（FK ON DELETE SET NULL
        # 已兜底，这里再保险清一次）
        await queries.unset_folder_for_docs(session, doc_ids)
        await queries.delete_folder_rows(session, report.cascaded_folder_ids)

    logger.info(
        "folder 级联删除完成：%s（%s），子 folder %d 个，文件 %d 个，错误 %d 个",
        folder_id, report.folder_name, len(report.cascaded_folder_ids) - 1,
        len(report.deleted_doc_ids), len(report.errors),
    )
    return report