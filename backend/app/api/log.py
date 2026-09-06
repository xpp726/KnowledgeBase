"""运行日志接口：文件列表 / 倒序分页条目 / 下载。

数据源 = log_config.py 持久化的日志文件（app.log 业务、access.log 访问，按天轮转）。
分页语义：最新在前，line_no 作游标（end_line 表示"读行号小于该值的更早数据"）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.schemas import LogEntriesOut, LogFileOut
from app.services import log_reader

router = APIRouter(prefix="/logs", tags=["log"])


@router.get("/files", response_model=list[LogFileOut])
async def list_log_files():
    return log_reader.list_log_files()


@router.get("/entries", response_model=LogEntriesOut)
async def log_entries(
    file: str = Query(..., description="日志文件名（来自 /files，如 app.log）"),
    level: str | None = Query(None, description="按级别过滤：INFO/WARNING/ERROR/DEBUG"),
    search: str | None = Query(None, description="消息关键词（大小写不敏感）"),
    end_line: int | None = Query(None, ge=1, description="游标：只读行号小于该值的更早数据"),
    limit: int = Query(100, ge=1, le=500, description="每页条数"),
):
    try:
        items, next_end_line = log_reader.read_entries(
            file,
            end_line=end_line,
            limit=limit,
            level=level,
            search=search,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="日志文件不存在") from None
    return {"items": items, "next_end_line": next_end_line}


@router.get("/download")
async def download_log(file: str = Query(..., description="日志文件名")):
    path = log_reader.resolve_path(file)
    if path is None:
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=file,
    )
