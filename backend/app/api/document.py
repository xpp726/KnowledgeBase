"""文档管理接口：分页列表 / 多文件上传（异步解析）/ 删除补偿 / 重试重解析。

上传语义（与前端约定）：
- POST /documents 只做"落存储 + 登记 pending"，毫秒级返回；
  解析由后端调度器异步执行（信号量限流，config.max_concurrent_ingest），
  前端轮询 GET /documents 观察状态推进。
- 同 folder 内 file_name 重复 → 该文件 rejected（错误码 409，folder 维度同名拒绝）。
- 同名（doc_id）已存在：done/failed → pending 重新入库（幂等覆盖）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.config import get_settings
from app.schemas import (
    DocumentListOut,
    DocumentSummaryOut,
    DocumentUploadResult,
    MoveDocumentResult,
    MoveDocumentsIn,
    OkResponse,
    ReprocessOut,
)
from app.services import document_service as doc_svc
from app.services import folder_service as folder_svc
from app.services.auth import User, get_current_user, require_editor
from app.services.document_service import DocumentNotFoundError, schedule_ingest

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["document"])

# 文件大小上限（字节）
_MAX_BYTES = settings.upload_max_mb * 1024 * 1024

# 内嵌预览支持的扩展名 → Content-Type（PDF / 图片 / TXT）
_PREVIEW_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".txt": "text/plain; charset=utf-8",
}



@router.get("", response_model=DocumentListOut)
async def list_documents(
    _: Annotated[User, Depends(get_current_user)],
    kb_id: str | None = Query(None, description="知识库 id，留空则全部"),
    folder_id: str | None = Query(
        None,
        description="folder id 过滤；留空返回 kb 下全部（不含 root 区分）。",
    ),
    status: str | None = Query(None, description="按状态筛选：pending/ingesting/embedding/done/failed"),
    search: str | None = Query(None, description="文件名模糊搜索"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        20, ge=1, le=20_000, description="每页条数；树状单表模式可一次性拉满（前端默认 20000）"
    ),
):
    return await doc_svc.list_documents_paginated(
        kb_id=kb_id,
        folder_id=folder_id,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )


# ⚠️ /summary 必须定义在 /{doc_id} 系列路由之前，否则 "summary" 会被 {doc_id} 捕获
@router.get("/summary", response_model=DocumentSummaryOut)
async def document_summary(
    _: Annotated[User, Depends(get_current_user)],
    kb_id: str | None = Query(None, description="知识库 id，留空则全部"),
):
    """文档状态计数（轻量，供前端轮询判断是否存在非终态文档）。"""
    return await doc_svc.count_documents_by_status(kb_id=kb_id)


@router.post("", response_model=list[DocumentUploadResult])
async def upload_documents(
    _: Annotated[User, Depends(require_editor)],
    files: list[UploadFile] = File(...),
    kb_id: str | None = Form(None, description="知识库 id，留空用 default"),
    folder_id: str | None = Form(
        None,
        description="folder id；留空用 kb 的默认 folder（系统自动建）",
    ),
):
    """多文件上传：逐个登记（落存储 + pending）并调度异步解析，立即返回登记结果。

    同 folder 内 file_name 重复 → 该文件 status="rejected" + 明确错误信息；
    不会阻塞其他文件（与 folders/{id}/upload 一致的"逐文件错误隔离"）。
    """
    results: list[dict] = []
    for f in files:
        data = await f.read()
        if len(data) > _MAX_BYTES:
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename or "unknown",
                    "folder_id": folder_id,
                    "status": "rejected",
                    "duplicated": False,
                    "error": f"文件超过 {settings.upload_max_mb}MB 上限",
                }
            )
            continue
        if not f.filename:
            continue
        try:
            row = await doc_svc.register_document(
                data, f.filename, kb_id=kb_id, folder_id=folder_id
            )
            schedule_ingest(row["doc_id"])
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "file_name": row["file_name"],
                    "folder_id": row.get("folder_id"),
                    "status": row["status"],
                    "duplicated": row.get("duplicated", False),
                    "error": row.get("error", ""),
                }
            )
        except folder_svc.FileNameConflictError as exc:
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename,
                    "folder_id": folder_id,
                    "status": "rejected",
                    "duplicated": False,
                    "error": str(exc),
                }
            )
        except folder_svc.FolderError as exc:
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename,
                    "folder_id": folder_id,
                    "status": "rejected",
                    "duplicated": False,
                    "error": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001 单个文件失败不阻塞其余文件
            logger.exception("登记失败 %s", f.filename)
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename,
                    "folder_id": folder_id,
                    "status": "rejected",
                    "duplicated": False,
                    "error": f"登记失败：{exc}",
                }
            )
    return results


@router.post("/move", response_model=list[MoveDocumentResult])
async def move_documents(
    payload: MoveDocumentsIn,
    _: Annotated[User, Depends(require_editor)],
):
    """批量移动文档到目标文件夹（同 kb、同名拒绝、逐文件错误隔离）。"""
    try:
        return await doc_svc.move_documents(payload.doc_ids, payload.target_folder_id)
    except folder_svc.FolderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except folder_svc.FolderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{doc_id}/reprocess", response_model=ReprocessOut)
async def reprocess_document(
    doc_id: str,
    _: Annotated[User, Depends(require_editor)],
):
    """重试（failed）或重新解析（done）：调度异步执行，立即返回，前端轮询状态。"""
    if await doc_svc.get_document(doc_id) is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 先置"排队中"（pending）：信号量排队期间状态对前端可见，轮询持续刷新；
    # 否则排队中文档保持终态，前端 summary 误判无进行中任务而停止轮询
    await doc_svc.mark_document_queued(doc_id)
    schedule_ingest(doc_id)
    return {"doc_id": doc_id, "status": "scheduled"}


@router.get("/{doc_id}/preview")
async def preview_document(
    doc_id: str,
    _: Annotated[User, Depends(get_current_user)],
):
    """内嵌预览：PDF/图片/TXT 直接回文件流（登录用户即可）；其余类型 415。"""
    try:
        doc, data = await doc_svc.read_document_file(doc_id)
    except doc_svc.DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ctype = _PREVIEW_CONTENT_TYPES.get((doc.get("file_ext") or "").lower())
    if ctype is None:
        raise HTTPException(status_code=415, detail="该文件类型暂不支持预览，可下载查看")
    return Response(content=data, media_type=ctype)


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    _: Annotated[User, Depends(get_current_user)],
):
    """下载原始文件（所有登录用户）；文件名用原始文件名（RFC 5987 编码，兼容中文）。"""
    try:
        doc, data = await doc_svc.read_document_file(doc_id)
    except doc_svc.DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = doc.get("file_name") or "download"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.delete("/{doc_id}", response_model=OkResponse)
async def delete_document(
    doc_id: str,
    _: Annotated[User, Depends(require_editor)],
):
    """删除补偿：向量 → 文件 → DB 定序删除，可幂等重入。"""
    report = await doc_svc.delete_document(doc_id)
    if not report.found:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not report.ok:
        raise HTTPException(
            status_code=500,
            detail=f"删除未完全成功：{'；'.join(report.errors) or 'DB 未删除'}",
        )
    return OkResponse(detail="deleted")
