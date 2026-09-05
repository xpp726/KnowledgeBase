"""轻量后台任务托管与启动恢复（单进程 asyncio，不引入 Celery 等重型执行器）。

- ``run_in_background``：托管 fire-and-forget 协程（如 Web 上传后异步入库），
  用集合持有强引用避免任务被 GC 提前回收，并统一记录异常，不静默吞掉。
- ``recover_stuck_documents``：应用启动时调用，把上次进程崩溃残留的
  pending/ingesting/embedding 文档按超时阈值标记 failed（业务判定在 document_service）。

用户已确认本期不抽象任务执行器，故这里只做最小调度，不做队列/持久化/分布式。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# 持有正在运行的后台任务强引用，防止事件循环弱引用导致任务中途被回收
_background_tasks: set[asyncio.Task] = set()


def run_in_background(coro) -> asyncio.Task:
    """托管一个后台协程，立即返回 Task；异常只记录、不影响主流程。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.exception() is not None:
            logger.error("后台任务异常: %r", t.exception(), exc_info=t.exception())

    task.add_done_callback(_on_done)
    return task


async def recover_stuck_documents() -> list[str]:
    """启动恢复：标记卡死文档为 failed。任何异常都不阻断应用启动。"""
    try:
        from app.services import document_service

        return await document_service.recover_stuck()
    except Exception as e:  # noqa: BLE001 启动恢复失败不应拖垮整个服务
        logger.error("启动卡死恢复失败（不影响启动）: %s", e)
        return []


def pending_count() -> int:
    """当前仍在运行的后台任务数（观测用）。"""
    return len(_background_tasks)
