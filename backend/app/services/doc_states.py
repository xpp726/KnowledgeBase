"""文档处理状态机（纯领域规则，零外部依赖，便于单测）。

状态流转（docs/后端结构调整方案.md §4）：

    None ──首次登记/直接处理──▶ PENDING / INGESTING
    PENDING ──▶ INGESTING ──▶ EMBEDDING ──▶ DONE
    任意处理态 ──异常──▶ FAILED（带 error）
    DONE / FAILED ──force 重跑──▶ INGESTING

设计要点：
- 这是**唯一**的合法迁移定义，ingestion 流水线与 document_service 改状态前都必须
  先经 ``assert_transition`` 校验，杜绝"任意状态互相跳"导致的脏状态。
- 删除文档不经过状态机（直接删行），DB 记录作为删除补偿的账本最后删除，因此不设
  DELETING 中间态，保持方案约定的 5 个状态。
"""

from __future__ import annotations

# ---- 状态常量（与 documents.status 列、历史代码字符串保持一致，勿随意改名） ----
PENDING = "pending"        # 已登记、原始文件已落存储，尚未解析
INGESTING = "ingesting"    # 解析 + 分块中
EMBEDDING = "embedding"    # 向量化 + 写 Milvus + 写 DB 中
DONE = "done"              # 入库完成，可被检索
FAILED = "failed"          # 流水线失败，带 error，可重试

ALL_STATES = frozenset({PENDING, INGESTING, EMBEDDING, DONE, FAILED})
# 仍在处理中、进程崩溃后可能卡住的状态（stuck 恢复扫描对象）
IN_PROGRESS = frozenset({PENDING, INGESTING, EMBEDDING})
TERMINAL = frozenset({DONE, FAILED})

# 合法迁移表：old -> {允许的 new}。None 表示 DB 中尚无该文档记录。
ALLOWED_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({PENDING, INGESTING}),
    PENDING: frozenset({INGESTING, FAILED}),
    INGESTING: frozenset({EMBEDDING, FAILED}),
    EMBEDDING: frozenset({DONE, FAILED}),
    # force 重新入库 / 同名文件重新上传：已完成的文档允许回到流水线起点或待处理
    DONE: frozenset({INGESTING, FAILED, PENDING}),
    FAILED: frozenset({PENDING, INGESTING}),
}


class IllegalTransitionError(RuntimeError):
    """不允许的状态跳转。"""


def can_transition(old: str | None, new: str) -> bool:
    """判断从 old 迁移到 new 是否合法。"""
    return new in ALLOWED_TRANSITIONS.get(old, frozenset())


def assert_transition(old: str | None, new: str) -> None:
    """校验迁移合法性，非法则抛 IllegalTransitionError。"""
    if not can_transition(old, new):
        raise IllegalTransitionError(f"非法文档状态迁移：{old!r} → {new!r}")


def is_stuck(status: str, updated_at: float, now: float, timeout_seconds: float) -> bool:
    """判断处于处理态且超过 timeout_seconds 未更新的文档是否卡死。

    单进程崩溃后，停在 INGESTING/EMBEDDING 的任务不会自行续跑，需启动时扫描，
    由 document_service 标记 FAILED 后再决定重试。终态/未超时不算卡住。
    """
    if status not in IN_PROGRESS:
        return False
    return (now - updated_at) > timeout_seconds
