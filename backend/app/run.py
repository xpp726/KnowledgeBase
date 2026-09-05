"""推荐启动入口：统一接管日志配置后启动 uvicorn。

用法（在 backend/ 目录下）：
    python -m app.run              # 生产/调试，日志落盘 data/logs/{app,access}.log
    python -m app.run --reload     # 开发热重载

说明：
- 必须经由本入口（或 uvicorn --log-config）启动，日志才会持久化。
  直接用 `uvicorn app.main:app` 会因 uvicorn 默认配置覆盖而只输出到控制台。
- 日志级别/目录/保留天数由 .env 的 LOG_LEVEL / LOG_DIR / LOG_RETENTION_DAYS 控制。
"""

from __future__ import annotations

import sys

import uvicorn

from app.config import get_settings
from app.log_config import build_logging_config

settings = get_settings()
log_config = build_logging_config(settings)

reload = "--reload" in sys.argv

uvicorn.run(
    "app.main:app",
    host=settings.host,
    port=settings.port,
    log_config=log_config,
    reload=reload,
    access_log=True,
)
