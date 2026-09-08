"""pytest 公共夹具与路径准备。

把 backend 根目录加入 sys.path，保证在任意工作目录执行 pytest 都能 import app；
测试全部使用 tests/fakes.py 的替身，不连接真实 BGE-M3 / Milvus / LLM / DB，离线可重复。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ⚠️ 测试库固定为 SQLite，与开发者本机 .env 的 DATABASE_URL 解耦。
# 原因：app.db 的 engine 在模块导入时按 DATABASE_URL 创建。若指向 MySQL（asyncmy），
# TestClient 触发 lifespan 的 create_all()/recover_stuck_documents() 会真的连 MySQL，
# 而 asyncmy 在 Windows ProactorEventLoop 下跨事件循环复用连接会抛
# "AttributeError: 'NoneType' object has no attribute 'send'"，且测试不再离线可重复。
# pydantic-settings 中环境变量优先级高于 .env 文件，故此处设置即可生效。
_TEST_DB = ROOT / "data" / "test_kb.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def _test_db_schema():
    """为测试库建表（幂等）。

    测试虽以 fakes 为主，但 config 等 API 会经应用 lifespan 触碰真实库
    （create_all / ensure_default_admin），因此必须保证表和默认管理员都存在。
    这里显式初始化，而非依赖开发者本机 data/kb.db 里遗留的表与账号，
    避免测试结果受本机开发数据影响。
    """
    from app.db import create_all  # 局部导入：确保上面的环境变量先生效
    from app.services.auth import ensure_default_admin

    async def _init() -> None:
        await create_all()
        # 默认管理员：受鉴权保护的接口（如 config API）依赖它登录
        await ensure_default_admin()

    asyncio.run(_init())
