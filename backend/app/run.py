"""推荐启动入口：统一接管日志配置后启动 uvicorn。

用法（在 backend/ 目录下）：
    python -m app.run              # 生产/调试，日志落盘 data/logs/{app,access}.log
    python -m app.run --reload     # 开发热重载（Windows 下 reload 重启依赖交互控制台）

说明：
- 必须经由本入口（或 uvicorn --log-config）启动，日志才会持久化。
  直接用 `uvicorn app.main:app` 会因 uvicorn 默认配置覆盖而只输出到控制台。
- 日志级别/目录/保留天数由 .env 的 LOG_LEVEL / LOG_DIR / LOG_RETENTION_DAYS 控制。
- 系统设置页"保存参数"的自动重启不依赖 uvicorn --reload：
  保存接口会 spawn 一个新进程（KB_WAIT_PORT=1）再退出自身，新进程等待旧进程
  释放端口后绑定启动（见 _wait_port_free / app.services.config_service._schedule_restart）。
"""

from __future__ import annotations

import os
import socket
import sys
import time

import uvicorn

from app.config import get_settings
from app.log_config import build_logging_config

settings = get_settings()
log_config = build_logging_config(settings)

reload = "--reload" in sys.argv


def _wait_port_free(port: int, timeout: float = 120.0) -> None:
    """KB_WAIT_PORT=1 时：轮询直到端口可绑定（旧进程已退出释放端口）再继续启动。"""
    if os.environ.get("KB_WAIT_PORT") != "1":
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return
            except OSError:
                time.sleep(0.3)
    raise SystemExit(f"waiting port {port} timeout")


if __name__ == "__main__":
    # 必须放 __main__ 守卫：--reload 模式下 uvicorn 用 multiprocessing spawn
    # 重启工作进程时会重新执行本模块，顶层调用会导致"bootstrap 未完成即 spawn"递归失败。
    _wait_port_free(settings.port)
    # reload_excludes：排除 data/（日志、SQLite、上传文件变化不应触发重启）
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=log_config,
        reload=reload,
        access_log=True,
        reload_excludes=["data/*", "data/**/*", "*.db", "*.db-*"],
    )
