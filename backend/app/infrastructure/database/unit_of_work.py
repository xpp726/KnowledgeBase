"""SQLAlchemy Unit of Work。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.repositories.conversation import SqlAlchemyConversationRepository
from app.infrastructure.database.repositories.document import SqlAlchemyDocumentRepository
from app.infrastructure.database.repositories.folder import SqlAlchemyFolderRepository
from app.infrastructure.database.repositories.knowledge_base import SqlAlchemyKnowledgeBaseRepository
from app.infrastructure.database.repositories.stats import SqlAlchemyStatsRepository
from app.infrastructure.database.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.database.session import get_session_factory


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory=None, *, auto_commit: bool = False):
        self._session_factory = session_factory
        self._auto_commit = auto_commit
        self.session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        factory = self._session_factory or get_session_factory()
        self.session = factory()
        self.documents = SqlAlchemyDocumentRepository(self.session)
        self.conversations = SqlAlchemyConversationRepository(self.session)
        self.folders = SqlAlchemyFolderRepository(self.session)
        self.knowledge_bases = SqlAlchemyKnowledgeBaseRepository(self.session)
        self.users = SqlAlchemyUserRepository(self.session)
        self.stats = SqlAlchemyStatsRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session is None:
            return
        if exc_type is not None:
            await self.session.rollback()
        elif self._auto_commit and not self._committed:
            await self.session.commit()
        elif not self._committed:
            await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork 尚未进入上下文")
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self.session is not None:
            await self.session.rollback()
