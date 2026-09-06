"""文档管理接口：分页列表 / 多文件上传（异步解析）/ 删除补偿 / 重试重解析。

上传语义（与前端约定）：
- POST /documents 只做"落存储 + 登记 pending"，毫秒级返回；
  解析由后端调度器异步执行（信号量限流，config.max_concurrent_ingest），
  前端轮询 GET /documents 观察状态推进。
- 同名文件：后端幂等覆盖（done/failed → pending 重新入库），响应带 duplicated 标志；
  前端上传前已按文件名查列表弹确认。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.config import get_settings
from app.schemas import DocumentListOut, DocumentUploadResult, OkResponse, ReprocessOut
from app.services import document_service as doc_svc
from app.services.auth import User, get_current_user, require_editor
from app.services.document_service import DocumentNotFoundError, schedule_ingest

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["document"])

# 文件大小上限（字节）
_MAX_BYTES = settings.upload_max_mb * 1024 * 1024


@router.get("", response_model=DocumentListOut)
async def list_documents(
    _: Annotated[User, Depends(get_current_user)],
    kb_id: str | None = Query(None, description="知识库 id，留空则全部"),
    status: str | None = Query(None, description="按状态筛选：pending/ingesting/embedding/done/failed"),
    search: str | None = Query(None, description="文件名模糊搜索"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    return await doc_svc.list_documents_paginated(
        kb_id=kb_id, status=status, search=search, page=page, page_size=page_size
    )


@router.post("", response_model=list[DocumentUploadResult])
async def upload_documents(
    _: Annotated[User, Depends(require_editor)],
    files: list[UploadFile] = File(...),
):
    """多文件上传：逐个登记（落存储 + pending）并调度异步解析，立即返回登记结果。"""
    results: list[dict] = []
    for f in files:
        data = await f.read()
        if len(data) > _MAX_BYTES:
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename or "unknown",
                    "status": "rejected",
                    "duplicated": False,
                    "error": f"文件超过 {settings.upload_max_mb}MB 上限",
                }
            )
            continue
        if not f.filename:
            continue
        try:
            row = await doc_svc.register_document(data, f.filename, kb_id=None)
            schedule_ingest(row["doc_id"])
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "file_name": row["file_name"],
                    "status": row["status"],
                    "duplicated": row.get("duplicated", False),
                }
            )
        except Exception as exc:  # noqa: BLE001 单个文件失败不阻塞其余文件
            logger.exception("登记失败 %s", f.filename)
            results.append(
                {
                    "doc_id": "",
                    "file_name": f.filename,
                    "status": "rejected",
                    "duplicated": False,
                    "error": f"登记失败：{exc}",
                }
            )
    return results


@router.post("/{doc_id}/reprocess", response_model=ReprocessOut)
async def reprocess_document(
    doc_id: str,
    _: Annotated[User, Depends(require_editor)],
):
    """重试（failed）或重新解析（done）：调度异步执行，立即返回，前端轮询状态。"""
    if await doc_svc.get_document(doc_id) is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    schedule_ingest(doc_id)
    return {"doc_id": doc_id, "status": "scheduled"}


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
