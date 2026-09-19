"""日志文件读取器：列表 / 尾部倒序分页 / 行解析 / 筛选。

数据源是 log_config.py 持久化的文件（app.log 业务日志、access.log HTTP 访问日志，
均按天轮转、保留 log_retention_days 天）。本模块把文件行解析成结构化条目，
供 /api/logs 接口倒序（最新在前）分页返回。

文件量级：单文件为当日日志（KB~MB），直接 readlines 全读 + 逆序过滤即可，
不引入 seek 分块读的复杂度；若未来单文件增长到数百 MB 再换 tail 实现。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 日志行分隔符：时间 | 级别 | 来源 | 消息（app 与 access 共用）
_SEP = " | "

# 级别白名单（其余按 OTHER 归入，展示为灰色）
KNOWN_LEVELS = ("INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL")

# uvicorn access log 默认带 ANSI 颜色码（如 \x1b[1m / \x1b[32m），剥离避免前端乱码
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class LogEntry:
    line_no: int  # 1-based 行号（物理文件行），用作分页游标
    ts: str = ""
    level: str = "OTHER"
    source: str = ""
    message: str = ""


def _parse_line(raw: str, file_type: str) -> LogEntry | None:
    """解析一行日志；空行返回 None，无法解析的行整体作为 message 保留（不丢行）。

    - app 行：`ts | LEVEL | module:line | message`（4 段）
    - access 行：`ts | LEVEL | client_addr - "request" status`（3 段，按 ` - ` 再拆）
    """
    line = _ANSI_RE.sub("", raw).rstrip("\n").rstrip("\r")
    if not line.strip():
        return None
    entry = LogEntry(line_no=0)
    parts = line.split(_SEP)
    if len(parts) >= 4 and len(parts[0]) >= 19:
        entry.ts = parts[0].strip()
        entry.level = parts[1].strip().upper()
        entry.source = parts[2].strip()
        entry.message = _SEP.join(parts[3:]).strip()
    elif len(parts) == 3 and len(parts[0]) >= 19:
        # access 型：`ts | LEVEL | client_addr - "GET /api/... HTTP/1.1" 200 OK`
        entry.ts = parts[0].strip()
        entry.level = parts[1].strip().upper()
        rest = parts[2].strip()
        if " - " in rest:
            client, req = rest.split(" - ", 1)
            entry.source = client.strip()
            entry.message = req.strip()
        else:
            entry.source = rest
            entry.message = ""
    else:
        # 容错：多行堆栈或异常格式 → 整行当消息
        entry.ts = ""
        entry.level = "OTHER"
        entry.source = "raw"
        entry.message = line.strip()
    if entry.level not in KNOWN_LEVELS:
        entry.level = "OTHER"
    return entry


def _file_type_of(name: str) -> str:
    return "access" if name.startswith("access") else "app"


def list_log_files() -> list[dict]:
    """扫描日志目录下所有 *.log* 文件（含历史轮转），按名称排序。"""
    log_dir: Path = settings.log_dir
    out: list[dict] = []
    if not log_dir.exists():
        return out
    for p in sorted(log_dir.iterdir(), key=lambda f: f.name):
        if not p.is_file() or ".log" not in p.name:
            continue
        out.append(
            {
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
                "is_rotated": "." in p.name.replace("access.log", "").replace("app.log", ""),
            }
        )
    return out


def resolve_path(file_name: str) -> Path | None:
    """按文件名解析到日志目录下的真实文件；防路径穿越（只允许 basename）。"""
    if not file_name or file_name != Path(file_name).name:
        return None
    p = settings.log_dir / file_name
    if p.is_file():
        return p
    return None


def read_entries(
    file_name: str,
    *,
    end_line: int | None = None,
    limit: int = 100,
    level: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int | None]:
    """倒序读取日志条目（最新在前）。

    - end_line=None：从文件末尾读 limit 条；
    - end_line=N：读行号 < N 的最近 limit 条。
    返回 (items, next_end_line)；next_end_line 为空表示已无更早数据。
    level/search 为可选过滤（过滤后仍凑满 limit 才返回，保证分页页大小稳定）。
    """
    path = resolve_path(file_name)
    if path is None:
        raise FileNotFoundError(f"日志文件不存在: {file_name}")
    file_type = _file_type_of(file_name)
    limit = max(1, min(int(limit), 500))

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    # 倒序遍历：物理行号从 total 递减到 1
    items: list[dict] = []
    line_no = total
    while line_no >= 1 and len(items) < limit:
        if end_line is not None and line_no >= end_line:
            line_no -= 1
            continue
        entry = _parse_line(lines[line_no - 1], file_type)
        current_line = line_no
        line_no -= 1
        if entry is None:
            continue
        if level and entry.level != level.upper():
            continue
        if search and search.lower() not in entry.message.lower():
            continue
        items.append(
            {
                "line_no": current_line,
                "ts": entry.ts,
                "level": entry.level,
                "source": entry.source,
                "message": entry.message,
            }
        )

    next_end_line = None
    if items:
        oldest = min(i["line_no"] for i in items)
        if oldest > 1:
            next_end_line = oldest - 1  # 下一批从最老行号-1 继续往前
    return items, next_end_line


def count_entries(file_name: str) -> int:
    path = resolve_path(file_name)
    if path is None:
        raise FileNotFoundError(f"日志文件不存在: {file_name}")
    with open(path, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)
