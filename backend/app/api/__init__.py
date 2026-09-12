"""HTTP 层（①）。

api_router 汇总所有子路由，由 main.py 统一挂载到 /api 前缀。
新增业务端点时：在本目录建对应模块 → 在此 include_router。
"""

from fastapi import APIRouter

from app.api.asr_ws import router as asr_ws_router
from app.api.auth_api import router as auth_router
from app.api.chat import router as chat_router
from app.api.conversation import router as conversation_router
from app.api.document import router as document_router
from app.api.folder import router as folder_router
from app.api.health import router as health_router
from app.api.knowledge_base import router as kb_router
from app.api.log import router as log_router
from app.api.stats import router as stats_router
from app.api.users_api import router as users_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
# ASR 语音输入代理（/asr/ws，JWT query 校验）
api_router.include_router(asr_ws_router)
# 认证（登录无需鉴权；/me、/change-password 内部加依赖）
api_router.include_router(auth_router)
# 用户管理（admin 专属）
api_router.include_router(users_router)
# 步骤 5：SSE 流式问答 + 会话管理（router 自带 /chat、/conversations 前缀）
api_router.include_router(chat_router)
api_router.include_router(conversation_router)
# 阶段 3：文档管理 + 知识库（router 自带 /documents、/kbs 前缀）
api_router.include_router(document_router)
api_router.include_router(kb_router)
# 阶段 3：文件夹树状组织（router 自带 /folders 前缀）
api_router.include_router(folder_router)
# 阶段 3：运行日志（router 自带 /logs 前缀）
api_router.include_router(log_router)
# 阶段 3：数据统计（router 自带 /stats 前缀）
api_router.include_router(stats_router)
# 阶段 3：系统设置（router 自带 /config 前缀）
from app.api.config_api import router as config_router

api_router.include_router(config_router)
