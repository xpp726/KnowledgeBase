"""集中构建 logging 配置（dictConfig），供 uvicorn 启动接管。

设计要点：
- 两个输出：console（stdout，开发期实时观察）+ 文件（持久化）。
- 文件按天轮转（when=midnight），保留 N 天（backupCount = settings.log_retention_days）。
- app.log 记录业务/uvicorn.error/第三方库日志；access.log 单独记录 HTTP 访问日志，
  避免两个 handler 写同一文件在轮转时产生竞争。
- 业务代码全程使用 logging.getLogger(__name__)，自动经 root 落到文件，无需改动业务代码。
- 第三方库（sqlalchemy/httpx/urllib3/pymilvus）默认 WARNING，避免噪声；
  需要排障时调高对应 logger 或整体 LOG_LEVEL。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings

FMT = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def build_logging_config(settings: Settings) -> dict[str, Any]:
    log_dir: Path = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    level = settings.log_level.upper()
    retention = settings.log_retention_days
    app_log = str(log_dir / "app.log")
    access_log = str(log_dir / "access.log")

    # 第三方库默认降到 WARNING，防止 SQL/HTTP 调试噪声淹没业务日志
    quiet_libs = ["sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool",
                  "httpx", "urllib3", "pymilvus"]

    loggers: dict[str, Any] = {
        "uvicorn": {"level": level, "handlers": ["console", "file"], "propagate": False},
        "uvicorn.error": {"level": level, "handlers": ["console", "file"], "propagate": False},
        # uvicorn.access 只落盘（access.log），不输出控制台：
        # 运行日志页持续轮询 /api/logs/entries，控制台打印访问日志会刷屏。
        "uvicorn.access": {"level": level, "handlers": ["access_file"], "propagate": False},
    }
    for lib in quiet_libs:
        loggers[lib] = {"level": "WARNING", "handlers": ["console", "file"], "propagate": False}

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": FMT, "datefmt": DATEFMT},
            # 访问日志使用 uvicorn 自带 formatter，正确渲染 %(client_addr)s 等占位符
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
                "datefmt": DATEFMT,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "level": level,
                "filename": app_log,
                "encoding": "utf-8",
                "when": "midnight",
                "interval": 1,
                "backupCount": retention,
                # delay=True：首条日志才打开文件。
                # --reload 时 reloader 父进程也会构建本配置，但它不写业务日志；
                # 延迟打开可避免父进程持有句柄，Windows 下多个进程写同一文件会令轮转 rename 失败。
                "delay": True,
            },
            "access_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "access",
                "level": level,
                "filename": access_log,
                "encoding": "utf-8",
                "when": "midnight",
                "interval": 1,
                "backupCount": retention,
                # delay=True：与 file 同理，避免 reloader 父进程持有 access.log 句柄。
                "delay": True,
            },
        },
        "loggers": loggers,
        "root": {
            "level": level,
            "handlers": ["console", "file"],
        },
    }
