"""文件夹管理接口：CRUD + 树构建 + 拖拽移动 + 上传（文件 / 目录）。

约定（与 docs/MEMORY 同步）：
- 树根是 kb；folder 隶属于 kb。
- folder 名同 parent 下唯一（FolderNameConflictError）。
- 嵌套深度最多 2 层（kb → 顶层 folder → 子 folder），文件落在子 folder 下。
- 系统默认 folder（is_system=True）禁止删除，允许重命名。
- 级联删除：BFS 取所有子孙 folder + 走 doc_svc.delete_document 完整删除补偿。
- 不参与 RAG 检索。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.config import get_settings
from app.schemas import (
    FolderCreate,
    FolderMove,
    FolderOut,
    FolderTree,
    FolderTreeNode,
    FolderUpdate,
    OkResponse,
)
from app.services import document_service as doc_svc
from app.services import folder_service as folder_svc
from app.services.auth import User, get_current_user, require_editor

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/folders", tags=["folder"])

# 文件大小上限（与 documents API 一致）
_MAX_BYTES = settings.upload_max_mb * 1024 * 1024


# ==================== 异常 → HTTP ====================

def _folder_error_to_http(e: folder_svc.FolderError) -> HTTPException:
    if isinstance(e, folder_svc.FolderNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, folder_svc.FolderNameConflictError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, folder_svc.FileNameConflictError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, folder_svc.FolderDepthLimitError):
        return HTTPException(status_code=422, detail=str(e))
    if isinstance(e, folder_svc.FolderSystemProtectedError):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, folder_svc.FolderKbMismatchError):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


# ==================== 树 ====================

@router.get("", response_model=FolderTree)
async def get_folder_tree(
    _: Annotated[User, Depends(get_current_user)],
    kb_id: str = Query(..., description="知识库 id"),
):
    """取某 kb 的 folder 嵌套树（含每个 folder 直属文件数）。"""
    items = await folder_svc.get_folder_tree(kb_id)
    return FolderTree(items=[FolderTreeNode(**n) for n in items])


# ==================== 创建 / 重命名 / 移动 ====================

@router.post("", response_model=FolderOut)
async def create_folder(
    body: FolderCreate,
    _: Annotated[User, Depends(require_editor)],
):
    """新建 folder。parent_id 为空 → 顶层 folder；非空 → 子 folder（深度 +1）。"""
    try:
        d = await folder_svc.create_folder(
            kb_id=body.kb_id,
            parent_id=body.parent_id,
            name=body.name.strip(),
        )
        return FolderOut(**d)
    except folder_svc.FolderError as e:
        raise _folder_error_to_http(e) from e


@router.patch("/{folder_id}", response_model=FolderOut)
async def rename_folder(
    folder_id: str,
    body: FolderUpdate,
    _: Annotated[User, Depends(require_editor)],
):
    """重命名（默认 folder 也允许）。"""
    try:
        d = await folder_svc.rename_folder(folder_id, body.name.strip())
        return FolderOut(**d)
    except folder_svc.FolderError as e:
        raise _folder_error_to_http(e) from e


@router.post("/{folder_id}/move", response_model=FolderOut)
async def move_folder(
    folder_id: str,
    body: FolderMove,
    _: Annotated[User, Depends(require_editor)],
):
    """拖拽移动：仅改 parent_id（同 kb 内）。默认 folder 不允许移动。"""
    try:
        d = await folder_svc.move_folder(folder_id, body.parent_id)
        return FolderOut(**d)
    except folder_svc.FolderError as e:
        raise _folder_error_to_http(e) from e


# ==================== 级联删除 ====================

@router.delete("/{folder_id}", response_model=OkResponse)
async def delete_folder_cascade(
    folder_id: str,
    _: Annotated[User, Depends(require_editor)],
):
    """级联删除 folder（含子 folder + 全部文件 + 向量 + 对象存储）。

    失败不阻塞：失败的 doc 会记入 report.errors，但外层 HTTP 返回成功（前端可继续刷）。
    """
    try:
        report = await folder_svc.delete_folder_cascade(folder_id)
    except folder_svc.FolderError as e:
        raise _folder_error_to_http(e) from e
    if not report.ok:
        # 部分成功：HTTP 200 + detail 提示（前端可重试）
        logger.warning(
            "folder 级联删除部分失败：%s（%s） errors=%d",
            folder_id, report.folder_name, len(report.errors),
        )
        return OkResponse(ok=True, detail=f"删除部分成功：{'；'.join(report.errors[:3])}")
    logger.info(
        "folder 级联删除完成：%s（%s） cascaded=%d 个，文件 %d 个",
        folder_id, report.folder_name,
        len(report.cascaded_folder_ids), len(report.deleted_doc_ids),
    )
    return OkResponse(detail="deleted")


# ==================== 上传（multipart 多文件） ====================

@router.post("/{folder_id}/upload", response_model=list)
async def upload_files_to_folder(
    folder_id: str,
    _: Annotated[User, Depends(require_editor)],
    files: list[UploadFile] = File(...),
):
    """把多个文件登记到指定 folder。同 folder 内同名 → 该文件 rejected。

    返回 list[DocumentUploadResult] 形态 dict；
    失败的文件不会阻塞其他文件（与 documents 一致的"逐文件错误隔离"约定）。
    """
    from app.db import get_async_session
    from app.models import queries

    # 校验 folder 存在（顺便拿 kb_id）
    async with get_async_session() as session:
        target = await queries.get_folder(session, folder_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"folder 不存在：{folder_id}")
        kb_id = target.kb_id

    results: list[dict] = []
    for f in files:
        if not f.filename:
            continue
        try:
            data = await f.read()
        except Exception as e:  # noqa: BLE001
            results.append({
                "doc_id": "",
                "file_name": f.filename,
                "folder_id": folder_id,
                "status": "rejected",
                "duplicated": False,
                "error": f"读取上传失败：{type(e).__name__}: {e}",
            })
            continue
        if len(data) > _MAX_BYTES:
            results.append({
                "doc_id": "",
                "file_name": f.filename,
                "folder_id": folder_id,
                "status": "rejected",
                "duplicated": False,
                "error": f"文件超过 {settings.upload_max_mb}MB 上限",
            })
            continue
        try:
            row = await doc_svc.register_document(
                data, f.filename, kb_id=kb_id, folder_id=folder_id
            )
            from app.services.document_service import schedule_ingest
            schedule_ingest(row["doc_id"])
            results.append({
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "folder_id": row.get("folder_id"),
                "status": row["status"],
                "duplicated": row.get("duplicated", False),
                "error": row.get("error", ""),
            })
        except folder_svc.FileNameConflictError as e:
            results.append({
                "doc_id": "",
                "file_name": f.filename,
                "folder_id": folder_id,
                "status": "rejected",
                "duplicated": False,
                "error": str(e),
            })
        except folder_svc.FolderError as e:
            results.append({
                "doc_id": "",
                "file_name": f.filename,
                "folder_id": folder_id,
                "status": "rejected",
                "duplicated": False,
                "error": str(e),
            })
        except Exception as e:  # noqa: BLE001 单文件失败不阻塞其余
            logger.exception("上传到 folder %s 失败 %s", folder_id, f.filename)
            results.append({
                "doc_id": "",
                "file_name": f.filename,
                "folder_id": folder_id,
                "status": "rejected",
                "duplicated": False,
                "error": f"登记失败：{type(e).__name__}: {e}",
            })
    return results


# ==================== 递归目录上传 ====================

@router.post("/{folder_id}/upload-directory", response_model=dict)
async def upload_directory_to_folder(
    folder_id: str,
    _: Annotated[User, Depends(require_editor)],
    files: list[UploadFile] = File(...),
    paths: str = Form(...),
):
    """递归上传一个目录（浏览器 webkitdirectory 触发）。

    paths 是 JSON 字符串：每个文件对应的**完整相对路径**（含子目录），如
    ``["工程/合同/A.pdf", "工程/合同/子目录/B.docx"]``。
    后端按路径段自动在目标 folder 下递归创建子 folder（深度限制 2 层：folder → 子 folder）。
    """
    import json as _json
    from app.db import get_async_session
    from app.models import queries

    # 1. 校验目标 folder
    async with get_async_session() as session:
        target = await queries.get_folder(session, folder_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"folder 不存在：{folder_id}")
        kb_id = target.kb_id

    # 2. 解析 paths
    try:
        rel_paths: list[str] = _json.loads(paths)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="paths 字段必须是合法 JSON 字符串数组")

    if len(rel_paths) != len(files):
        raise HTTPException(
            status_code=422,
            detail=f"paths 数量 ({len(rel_paths)}) 与 files 数量 ({len(files)}) 不一致",
        )

    # 3. 递归创建 sub-folder + 注册文件
    # cache: {parent_folder_id: {dir_name: child_folder_id}}（按 kb 维度，跨 parent 共享）
    sub_cache: dict[str | None, dict[str, str]] = {}

    async def _ensure_subfolder(parent_id: str | None, name: str) -> str | None:
        key = (parent_id, name)
        if key in sub_cache.get(parent_id, {}):
            return sub_cache[parent_id][name]
        try:
            d = await folder_svc.create_folder(
                kb_id=kb_id, parent_id=parent_id, name=name
            )
            sub_cache.setdefault(parent_id, {})[name] = d["folder_id"]
            return d["folder_id"]
        except folder_svc.FolderNameConflictError:
            # 已存在（递归并发场景）：按 sibling name 找
            async with get_async_session() as session:
                exist = await queries.find_folder_by_sibling_name(
                    session, kb_id, parent_id, name
                )
                if exist is not None:
                    sub_cache.setdefault(parent_id, {})[name] = exist.folder_id
                    return exist.folder_id
            return None
        except folder_svc.FolderError as e:
            logger.warning("创建 sub-folder 失败：%s/%s → %s", parent_id, name, e)
            return None

    uploaded: list[dict] = []
    rejected: list[dict] = []
    for file, rel in zip(files, rel_paths):
        if not file.filename:
            continue
        # 安全：禁 .. / 绝对路径
        rel_norm = rel.replace("\\", "/").strip("/")
        if ".." in rel_norm.split("/"):
            rejected.append({
                "file_name": rel, "status": "rejected", "error": "路径含 ..",
            })
            continue
        parts = rel_norm.split("/")
        # 路径前缀（除最后文件名）的目录都要建出来；最后一段是文件名（不一定是，
        # 因为 webkitdirectory 路径可能本身就含文件名）
        # 约定：rel 是完整相对路径（含文件名），目录为除最后一段
        if len(parts) <= 1:
            target_folder_id = folder_id  # 直接进目标 folder
        else:
            dir_parts = parts[:-1]
            cur_parent = folder_id
            cur_folder_id = folder_id
            try:
                for d in dir_parts:
                    cur_folder_id = await _ensure_subfolder(cur_parent, d)
                    if cur_folder_id is None:
                        break
                    cur_parent = cur_folder_id
            except folder_svc.FolderError as e:
                rejected.append({
                    "file_name": rel, "status": "rejected",
                    "error": f"目录创建失败：{e}",
                })
                continue
            target_folder_id = cur_folder_id or folder_id

        # 注册文件
        try:
            data = await file.read()
        except Exception as e:  # noqa: BLE001
            rejected.append({
                "file_name": rel, "folder_id": target_folder_id,
                "status": "rejected", "error": f"读取失败：{type(e).__name__}: {e}",
            })
            continue
        if len(data) > _MAX_BYTES:
            rejected.append({
                "file_name": rel, "folder_id": target_folder_id,
                "status": "rejected", "error": f"文件超过 {settings.upload_max_mb}MB 上限",
            })
            continue
        try:
            row = await doc_svc.register_document(
                data, parts[-1], kb_id=kb_id, folder_id=target_folder_id
            )
            from app.services.document_service import schedule_ingest
            schedule_ingest(row["doc_id"])
            uploaded.append({
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "folder_id": row.get("folder_id"),
                "status": row["status"],
                "duplicated": row.get("duplicated", False),
                "path": rel,
            })
        except folder_svc.FileNameConflictError as e:
            rejected.append({
                "file_name": parts[-1], "folder_id": target_folder_id,
                "status": "rejected", "error": str(e), "path": rel,
            })
        except Exception as e:  # noqa: BLE001
            logger.exception("递归上传失败 %s", rel)
            rejected.append({
                "file_name": parts[-1], "folder_id": target_folder_id,
                "status": "rejected",
                "error": f"{type(e).__name__}: {e}",
                "path": rel,
            })

    return {
        "uploaded": uploaded,
        "rejected": rejected,
        "summary": {
            "uploaded_count": len(uploaded),
            "rejected_count": len(rejected),
            "created_folder_ids": sorted({
                fid for sub in sub_cache.values() for fid in sub.values()
            }),
        },
    }