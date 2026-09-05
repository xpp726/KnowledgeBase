"""SQLAlchemy 2.0 ORM 模型。

所有模型继承 Base，表结构与旧 db.py 裸 SQL 层兼容，并新增 kb_id 多知识库维度。
时间戳沿用旧设计：REAL 列存 time.time() 浮点秒数，保证与现有数据兼容。
"""

from app.models.base import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.conversation import Conversation, Message
from app.models.log import QueryLog

__all__ = [
    "Base",
    "KnowledgeBase",
    "Document",
    "Chunk",
    "Conversation",
    "Message",
    "QueryLog",
]
