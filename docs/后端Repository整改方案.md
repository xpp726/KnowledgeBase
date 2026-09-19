# 后端 Repository 分层整改方案

> 状态：已完成。阶段 0-4 已完成，兼容层已收敛删除，依赖扫描、编译检查和全量回归均已通过。
> 
> 本文是当前后端整改的实施依据。它在保留现有 API、数据库表、文档状态机和外部服务行为的前提下，引入业务型 Repository、Unit of Work 和外部服务 Port/Adapter，收敛数据访问边界，降低后续扩展和测试成本。

## 1. 背景与目标

当前后端已经形成了 `api / services / models` 的基础分层，但数据访问仍然以 `app/models/queries.py` 为中心，业务 Service 直接创建 SQLAlchemy session，并且部分 API 直接访问数据库。随着文档、文件夹、知识库、会话、统计和用户管理继续扩展，现有方式会逐渐出现以下问题：

- HTTP 路由、业务编排和 SQL 查询边界不稳定；
- `models/queries.py` 持续膨胀，多个业务修改同一个文件；
- Service 直接依赖 SQLAlchemy ORM 和数据库 session，难以独立测试；
- 相同的过滤、权限范围、分页和状态条件容易在不同接口重复实现；
- 多步业务流程的事务边界不容易确认；
- MySQL、Milvus、MinIO、Embedding 和 LLM 的依赖混在业务代码中；
- 新业务需要同时理解 API、ORM、查询函数和外部客户端的实现细节。

本次整改目标：

1. API 层只处理协议、参数、权限依赖、响应和错误映射。
2. Application Service 负责业务用例和流程编排。
3. Repository 负责结构化数据的查询和持久化。
4. Unit of Work 负责数据库事务边界。
5. 外部系统通过 Port/Adapter 接入，不把外部客户端实现泄漏到业务层。
6. 业务服务可以使用 Fake Repository、Fake Storage、Fake VectorStore 独立测试。
7. 不改变现有 API 路径、请求响应结构、数据库表语义和外部服务协议。

## 当前实施进度

### 已完成

- `domain/` 已建立业务 Repository Protocol、领域记录和文档状态机；文档、会话、知识库、文件夹、用户的 SQLAlchemy 结果已转换为 `*Record`，Application 不再接收 ORM 对象。
- `infrastructure/database/` 已集中 ORM Model、业务 Repository 和 `SqlAlchemyUnitOfWork`；显式提交、短事务自动提交和异常回滚边界已统一。
- `application/` 已迁移用户、统计、文件夹、文档入库、文档管理、会话、RAG 和任务用例；文档移动、卡死恢复等写操作通过 Repository 方法完成，不再直接使用 `uow.session`。
- `domain/ports/` 已建立 FileStorage、VectorStore、Embedder、LLM Port；`bootstrap/container.py` 统一装配生产实现，解析器和分块器也通过组合根延迟装配。
- Milvus、MinIO、Embedding、LLM、解析器、健康检查、配置管理和日志读取已迁移到 `infrastructure/`；旧 `app/services` 兼容入口已删除。
- API 已切换到 Application Service 或 Infrastructure 门面，生产代码中不再直接导入旧 `app.services`、`app.models` 或 `app.db`。
- 已完成静态依赖扫描、Python 编译检查和全量回归：`182 passed, 2 warnings`。警告来自现有 FastAPI/Starlette 与 httpx/anyio 依赖弃用提示，不是本次整改引入。

### 收尾结果

- `app/db.py`、`app/models/*`、`app/models/queries.py`、旧认证/文档/文件夹/会话 Service 和旧状态机入口已删除。
- 测试夹具已直接注入 `infrastructure.database.session`，认证测试已改为验证 `UserApplicationService`、`UserRecord` 和 `core.security`。
- Alembic 已直接从 `app.infrastructure.database.models` 收集元数据；脚本、测试和生产代码不再依赖旧路径。
- Repository、Unit of Work、Application Service、Fake Port 和核心 API 已通过全量回归：`182 passed, 2 warnings`。
- 新增 `scripts/verify_backend.py` 作为部署/CI 验收入口，统一执行 Alembic 检查、编译检查、旧依赖扫描、真实健康检查和全量测试。

已完成：

- 新增 `domain / application / infrastructure / core` 基础目录；
- 新增业务型 `UserRepository`、`StatsRepository`、`FolderRepository`、`DocumentRepository`、`KnowledgeBaseRepository`、`ConversationRepository` 接口；
- 新增 SQLAlchemy User/Stats/Folder/Document/KnowledgeBase/Conversation Repository 实现；
- 新增 SQLAlchemy Unit of Work，统一新链路的 session 生命周期和显式提交；
- 新增用户和统计 Application Service；
- `/auth`、`/users`、`/stats` 改为通过新 Application Service 访问数据库；
- API 鉴权读取统一通过 User Repository，JWT 工具下沉到 `core/security.py`；
- 文件夹上传接口的 folder 查询改为 Folder Repository/Application Service；
- 文档登记、列表、移动、删除补偿、卡死恢复和入库流水线改为通过 Document/Folder/KnowledgeBase Repository 访问数据；
- 文件夹完整 CRUD 和级联删除改为通过 Folder Repository 访问数据；
- 会话、消息和问答日志写入改为通过 Conversation Repository，保留 assistant message + query log 同事务边界；
- SQLAlchemy ORM Model 已下沉到 `app/infrastructure/database/models`，旧 `app/models/*` 已删除；
- engine、session factory、建表和 schema patch 已下沉到 `app/infrastructure/database/session.py`，`app.db` 已删除；
- 默认管理员初始化已迁移为 `application/users/bootstrap.py` 用例，启动装配不再依赖旧认证 Service；
- 旧 `services.auth` 已移除重复的密码/JWT实现，统一复用 `core/security.py`，生产代码不再依赖旧认证入口；
- 文件夹完整 CRUD、树构建、移动和级联删除已迁移到 `application/folders/service.py`，旧 Service 入口已删除；
- 文档登记、列表、移动、删除补偿、重试、卡死恢复和启动知识库初始化已迁移到 `application/documents/service.py`，旧 Service 入口已删除；
- 会话创建、历史读取、消息与 query log 写入、会话 CRUD 已迁移到 `application/conversations/service.py`，旧 Service 入口已删除；
- 文档入库已迁移到 `application/documents/ingestion.py`；检索和 RAG 问答已迁移到 `application/rag/`；启动任务已迁移到 `application/tasks/service.py`；
- Storage、Milvus、Embedding、LLM、解析器、OCR 和分块实现已迁移到 `infrastructure`，Application 通过 `domain/ports` 使用外部能力；
- 健康检查已迁移到 `infrastructure/health/checks.py`，API 不再从 `services.health` 读取基础设施探测实现；
- 会话 Application Service 已改为通过统一 UoW 管理读写事务，API 核心路由已脱离旧文档兼容 Service；
- HTTP Schema 已按业务拆分到 `app/schemas/`，统一导出入口只负责聚合，不再保留旧单文件模块；
- 新增 Application Service、启动初始化和 Unit of Work 提交/回滚测试；外部适配器与分层迁移专项测试已通过，后端全量回归为 `182 passed, 2 warnings`。

尚未完成：

- 无。后续仅按新增业务继续遵守本方案的分层边界和依赖方向。

## 2. 非目标与边界

本次整改不做以下事情：

- 不引入通用 `GenericRepository[T]`，不把所有表强行包装成相同的 CRUD 接口；
- 不为了形式引入完整、重量级的 DDD 聚合体系；
- 不引入 Celery、消息队列或分布式事务；
- 不改变 MySQL、Milvus、MinIO、BGE-M3 和 LLM 的选型；
- 不把 Milvus、MinIO、Embedding、LLM 误命名为 SQL Repository；
- 不通过 Repository 解决 MySQL、Milvus、对象存储之间的原子提交问题；
- 不在本次整改中改变前端接口契约。

文档入库仍然是跨系统流程：MySQL、对象存储和 Milvus 无法共享一个事务。现有的状态机、幂等处理、失败记录、补偿删除和重试机制必须保留。Unit of Work 只保证单个 MySQL 事务范围。

## 3. 目标依赖方向

```text
HTTP / WebSocket / CLI
          |
          v
api/                       协议层
  参数校验、权限依赖、响应、SSE/WS、HTTP 错误映射
          |
          v
application/               用例层
  文档上传、文档删除、会话问答、用户管理、统计等业务流程
          |
          +----------------------+
          |                      |
          v                      v
domain/ ports              Unit of Work / Repository interfaces
  状态机、领域异常、        业务数据访问抽象、外部系统抽象
  业务值对象
          |                      |
          +----------+-----------+
                     v
infrastructure/            技术实现层
  SQLAlchemy Repository、Unit of Work、Milvus、MinIO、LLM、Embedding、解析器
                     |
                     v
MySQL / Milvus / MinIO / BGE-M3 / LLM
```

依赖规则：

| 层 | 可以依赖 | 禁止依赖 |
|---|---|---|
| `api` | `application`、`schemas`、认证依赖 | `db`、SQLAlchemy Model、Repository 实现、Milvus、MinIO |
| `application` | `domain`、Repository 接口、外部 Port、DTO | FastAPI、HTTPException、SQLAlchemy、具体 Milvus/MinIO 实现 |
| `domain` | Python 标准库、领域类型 | FastAPI、SQLAlchemy、数据库、网络客户端 |
| `infrastructure` | SQLAlchemy、FastAPI 外部协议客户端、配置 | API 响应和业务用例编排 |
| `schemas` | Pydantic | 数据库查询、业务流程 |
| `scripts` | Application Service、基础设施启动入口 | 复制业务逻辑 |

原则上依赖方向只能从上向下。Application Service 依赖接口，运行时由启动装配层注入具体实现。

## 4. 目标目录结构

```text
backend/app/
├── main.py                         # FastAPI 应用和生命周期装配
├── run.py                          # uvicorn 启动入口
├── config.py                       # Pydantic Settings，保留现有配置入口
├── log_config.py                   # 日志配置
├── api/                            # HTTP / WebSocket 协议层
│   ├── __init__.py
│   ├── dependencies.py             # 当前用户、应用容器、UoW 依赖
│   ├── auth.py
│   ├── users.py
│   ├── chat.py
│   ├── conversations.py
│   ├── documents.py
│   ├── folders.py
│   ├── knowledge_bases.py
│   ├── logs.py
│   ├── stats.py
│   ├── config.py
│   ├── health.py
│   └── asr_ws.py
├── schemas/                        # HTTP 请求/响应模型，按业务拆分
│   ├── __init__.py
│   ├── common.py
│   ├── auth.py
│   ├── users.py
│   ├── chat.py
│   ├── conversations.py
│   ├── documents.py
│   ├── folders.py
│   ├── knowledge_bases.py
│   ├── logs.py
│   ├── stats.py
│   └── config.py
├── application/                    # 业务用例和流程编排
│   ├── __init__.py
│   ├── auth/
│   │   ├── service.py
│   │   └── dto.py
│   ├── users/
│   │   └── service.py
│   ├── documents/
│   │   ├── service.py              # 文档登记、列表、删除、重试、恢复
│   │   ├── ingestion.py            # 解析、分块、向量化、落库编排
│   │   └── dto.py
│   ├── folders/
│   │   └── service.py
│   ├── knowledge_bases/
│   │   └── service.py
│   ├── conversations/
│   │   └── service.py
│   ├── rag/
│   │   ├── service.py              # RAG / 通用问答用例
│   │   └── retrieval.py             # 检索编排
│   ├── stats/
│   │   └── service.py
│   └── tasks/
│       └── service.py              # 单进程后台任务和启动恢复
├── domain/                         # 与技术实现无关的业务规则
│   ├── documents/
│   │   ├── entities.py
│   │   ├── states.py
│   │   ├── errors.py
│   │   └── repositories.py         # DocumentRepository / ChunkRepository 接口
│   ├── folders/
│   │   ├── errors.py
│   │   └── repositories.py
│   ├── conversations/
│   │   └── repositories.py
│   ├── users/
│   │   ├── errors.py
│   │   └── repositories.py
│   └── ports/
│       ├── vector_store.py
│       ├── file_storage.py
│       ├── embedding.py
│       └── llm.py
├── infrastructure/                 # 具体技术实现
│   ├── database/
│   │   ├── session.py              # engine、session factory
│   │   ├── models/                 # SQLAlchemy ORM Model
│   │   ├── repositories/           # SQLAlchemy Repository 实现
│   │   │   ├── document.py
│   │   │   ├── folder.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── conversation.py
│   │   │   ├── user.py
│   │   │   └── stats.py
│   │   └── unit_of_work.py
│   ├── vectorstore/
│   │   └── milvus.py
│   ├── storage/
│   │   ├── provider.py              # Local / MinIO 适配器
│   │   └── __init__.py
│   ├── embedding/
│   │   └── bge_m3.py
│   ├── llm/
│   │   ├── openai_compatible.py     # Qwen / DeepSeek 等兼容端点
│   │   └── __init__.py
│   ├── parsing/
│   │   ├── chunker.py
│   │   ├── ocr.py
│   │   └── parsers/
│   └── health/
│       └── checks.py
└── bootstrap/
    ├── container.py                # 生产依赖装配
    └── lifespan.py                 # 启动恢复、默认数据初始化
```

说明：当前 `app/models/`、`app/db.py` 和 `app/services/` 不会一次性机械搬移。整改时按上述职责迁移，最终由 `infrastructure/database` 和 `application` 接管。这样能减少移动文件但边界不变的无效工作。

## 5. Repository 设计原则

### 5.1 按业务能力设计，不按通用 CRUD 设计

不采用以下模式：

```python
class GenericRepository:
    async def create(...): ...
    async def get(...): ...
    async def update(...): ...
    async def delete(...): ...
```

不同业务的查询条件和事务语义不同，通用 CRUD 只会隐藏实现，不能表达业务意图。

采用业务型接口，例如：

```python
class DocumentRepository(Protocol):
    async def get_by_id(self, doc_id: str) -> DocumentRecord | None: ...

    async def find_in_folder_by_name(
        self, kb_id: str, folder_id: str, file_name: str
    ) -> DocumentRecord | None: ...

    async def list_page(
        self,
        *,
        kb_id: str | None,
        folder_id: str | None,
        status: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> DocumentPage: ...

    async def count_by_status(self, kb_id: str) -> DocumentStatusCount: ...

    async def update_status(self, doc_id: str, status: str, **fields) -> None: ...

    async def delete(self, doc_id: str) -> None: ...
```

Repository 可以提供查询和持久化操作，但不应该决定：

- 文档是否允许重新上传；
- 删除顺序是向量、文件还是数据库；
- 当前用户是否拥有管理员权限；
- 入库失败后是否重试；
- 一个完整业务用例要调用哪些外部服务。

这些规则属于 Application Service 或 Domain。

### 5.2 Repository 不创建 session，不提交事务

统一约定：

- Repository 由 Unit of Work 创建；
- Repository 使用 Unit of Work 提供的 session；
- Repository 不自行创建 session；
- Repository 不调用 `commit()`；
- Repository 可以 `flush()`，但提交由 Unit of Work 控制；
- 查询 Repository 可以返回业务记录 DTO，而不是让上层依赖 ORM 关系加载行为。

### 5.3 读写接口按实际需求拆分

普通实体可以使用一个 Repository；统计和复杂报表使用专门的查询 Repository：

```text
DocumentRepository       文档元数据和状态
ChunkRepository           chunk 原文和入库关联
FolderRepository          文件夹树、层级和计数
KnowledgeBaseRepository  知识库及文档计数
ConversationRepository   会话、消息、引用
UserRepository            用户和角色
QueryLogRepository       问答查询日志
StatsRepository          统计聚合读模型
```

统计查询不应该为了“统一”塞进 `DocumentRepository` 或通用 Repository。

### 5.4 ORM Model 不作为业务接口扩散

SQLAlchemy Model 仅在 `infrastructure/database` 内部使用。上层使用以下类型之一：

- 不需要复杂行为的只读记录 DTO；
- 轻量 Domain Entity；
- 专门的分页结果和统计结果对象。

如果短期为了降低迁移成本，Application Service 暂时接收 ORM Model，必须将其视为过渡状态，禁止新的 Service 继续直接导入 ORM Model。

## 6. Unit of Work 设计

Unit of Work 负责一个 MySQL 事务中的多个 Repository 协作：

```python
class UnitOfWork(Protocol):
    documents: DocumentRepository
    chunks: ChunkRepository
    folders: FolderRepository
    conversations: ConversationRepository
    users: UserRepository
    logs: QueryLogRepository

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

SQLAlchemy 实现大致遵循：

```python
async with uow_factory() as uow:
    document = await uow.documents.get_by_id(doc_id)
    await uow.documents.update_status(doc_id, "embedding")
    await uow.commit()
```

异常时由 Unit of Work 回滚。Application Service 决定一个用例的事务边界。

文档入库需要特别处理：

- `pending` 登记可以是一个独立事务；
- 每次状态推进可以是独立短事务；
- MySQL 写入 chunk 和文档元数据可以在同一个事务中；
- Milvus 和对象存储操作不放进 MySQL 事务假设中；
- 外部系统失败必须写入 `failed` 和错误信息，并保留补偿/重试能力。

不能为了使用 Unit of Work 而把整个文件解析和向量化过程包在一个长时间数据库事务中。

## 7. 外部系统 Port/Adapter

Repository 只覆盖结构化持久化。外部系统使用接口和适配器：

```python
class VectorStore(Protocol):
    async def upsert(self, chunks: list[VectorChunk]) -> None: ...
    async def search(self, query, *, kb_id: str, top_k: int) -> list[VectorHit]: ...
    async def delete_document(self, doc_id: str) -> int: ...

class FileStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...

class LLMProvider(Protocol):
    async def stream(self, messages, **options): ...
```

具体实现：

```text
MilvusVectorStore
LocalFileStorage
MinioFileStorage
BgeM3EmbeddingProvider
QwenLLMProvider
DeepSeekLLMProvider
```

业务层只依赖接口，不直接 import `pymilvus`、`minio`、`httpx` 或具体 LLM SDK。

## 8. 典型调用链

### 8.1 文档上传

```text
POST /api/documents
  -> api.documents.upload
  -> DocumentApplicationService.register
  -> FolderRepository 检查 folder
  -> DocumentRepository 检查同名文件
  -> FileStorage 保存原文件
  -> UnitOfWork 写入 pending
  -> TaskService 调度 ingest
```

### 8.2 文档入库

```text
IngestionService.ingest
  -> FileStorage 读取文件
  -> ParserRegistry 解析
  -> Chunker 分块
  -> EmbeddingProvider 向量化
  -> VectorStore 写入 Milvus
  -> UnitOfWork 写入 Document / Chunk
  -> DocumentRepository 更新 done
```

### 8.3 问答

```text
GET /api/chat/stream
  -> api.chat
  -> ChatApplicationService
  -> ConversationRepository 读取历史
  -> EmbeddingProvider 生成查询向量
  -> VectorStore 检索
  -> LLMProvider 流式生成
  -> ConversationRepository 写入消息
  -> QueryLogRepository 写入日志
  -> SSE 返回
```

## 9. 现有模块迁移映射

| 当前位置 | 目标位置 | 迁移说明 |
|---|---|---|
| `app/api/*.py` | `app/api/*.py` | 保留 API 层，但清理数据库和业务编排；统一命名 |
| `app/schemas.py` | `app/schemas/*.py` | 已按业务拆分，旧单文件入口已删除 |
| `app/models/*.py` | `app/infrastructure/database/models/` | ORM Model 下沉到持久化实现层 |
| `app/models/queries.py` | `app/infrastructure/database/repositories/` | 按业务拆分为 Repository 实现 |
| `app/db.py` | `app/infrastructure/database/session.py` | engine、session 工厂和 schema 初始化已下沉，旧文件已删除 |
| `app/services/document_service.py` | `app/application/documents/service.py` | 文档登记、查询、删除补偿和重试已迁移，旧文件已删除 |
| `app/services/conversation_service.py` | `app/application/conversations/service.py` | 会话、消息和查询日志编排已迁移，旧文件已删除 |
| `app/services/folder_service.py` | `app/application/folders/service.py` | 文件夹 CRUD、树构建和级联删除已迁移，旧文件已删除 |
| `app/services/ingestion.py` | `app/application/documents/ingestion.py` | 入库流程编排保留 |
| `app/services/conversation_service.py` | `app/application/conversations/service.py` | 会话用例下沉 |
| `app/services/rag.py` | `app/application/rag/service.py` | RAG 用例编排下沉 |
| `app/services/retrieval.py` | `app/application/rag/retrieval.py` | 检索编排依赖 Embedding/VectorStore Port |
| `app/services/vectorstore.py` | `app/infrastructure/vectorstore/milvus.py` | Milvus 具体实现 |
| `app/services/storage.py` | `app/infrastructure/storage/provider.py` | Local/MinIO 具体实现 |
| `app/services/embedding.py` | `app/infrastructure/embedding/bge_m3.py` | BGE-M3 具体实现 |
| `app/services/llm.py` | `app/infrastructure/llm/` | LLM provider 具体实现 |
| `app/services/health.py` | `app/infrastructure/health/checks.py` | 外部依赖健康检查适配器 |
| `app/services/parsers/` | `app/infrastructure/parsing/` | 解析器是技术适配，不属于业务 Service |
| `app/services/doc_states.py` | `app/domain/documents/states.py` | 纯状态机属于 Domain |
| `app/services/tasks.py` | `app/application/tasks/service.py` | 单进程任务托管和恢复 |
| `app/services/auth.py` | `app/application/auth/` + `core/security.py` | JWT/密码技术与用户业务拆开 |

## 10. 实施阶段

### 阶段 0：冻结基线

- 保留当前 API、数据库和前端行为不变；
- 记录后端全量测试基线；
- 补充关键链路测试：上传、入库、删除补偿、问答、用户权限、统计；
- 用静态搜索记录当前 `api -> db/models/queries` 依赖。

### 阶段 1：目录和契约落地

- 新建 `application`、`domain`、`infrastructure`、`schemas` 目录；
- 拆分 Pydantic schema；
- 定义 Repository、Unit of Work、VectorStore、FileStorage、Embedding、LLM 接口；
- 暂不改变现有业务实现，只建立接口和装配入口。

### 阶段 2：持久化层迁移

- 将 ORM Model 移入 `infrastructure/database/models`（已完成，旧路径已删除）；
- 将 `models/queries.py` 按业务拆成 Repository 实现（已完成，旧查询层已删除）；
- 实现 SQLAlchemy Unit of Work；
- 统一 Repository 不创建 session、不 commit；
- 为 Repository 编写数据库集成测试。

### 阶段 3：核心业务迁移

按风险从低到高迁移：

1. 知识库和文件夹；
2. 用户和认证；
3. 会话和查询日志；
4. 文档列表、状态和删除；
5. 文档入库和补偿；
6. RAG 问答和流式会话。

每迁移一个模块，API 只调用 Application Service，并删除该模块对 `db`、`models` 和 `queries` 的直接依赖。

### 阶段 4：外部适配器迁移

- 将 Milvus、MinIO、Embedding、LLM 和解析器移入 `infrastructure`（已完成首轮迁移）；
- Application Service 只依赖 Port（核心文档入库、检索和 RAG 已完成）；
- 统一由 `bootstrap/container.py` 装配生产实现；
- 测试使用 Fake 实现或 Mock Port。

### 阶段 5：清理和验收

- 删除旧的 `app/models/queries.py`；
- 删除 Service 中自行创建 session 的代码；
- 删除 API 中所有数据库直接访问；
- 删除重复的旧 schema 和兼容别名；
- 完成导入依赖扫描、全量测试和真实链路回归。

## 11. 测试策略

### Domain 测试

不连接数据库，测试：

- 文档状态迁移；
- 非法状态跳转；
- 文件夹层级规则；
- 领域异常和边界条件。

### Application Service 测试

使用 Fake Repository 和 Fake 外部 Port，测试：

- 上传登记和重复文件；
- 文档删除补偿顺序；
- 入库失败和重试；
- 会话权限隔离；
- RAG 无命中和流式结束；
- 外部服务失败后的状态写入。

### Repository 集成测试

使用测试 MySQL，测试：

- 查询过滤和分页；
- 用户/知识库隔离；
- 统计聚合口径；
- Unit of Work 提交和回滚；
- 文档与 chunk 的事务一致性。

### API 回归测试

保留现有 FastAPI 接口测试，重点确认：

- 路径和 HTTP 方法不变；
- 请求响应字段不变；
- 认证和角色权限不变；
- SSE 事件顺序不变；
- 错误状态码和错误消息语义不变。

## 12. 验收标准

整改完成后，必须满足：

- `app/api` 不再直接导入 `app.db`、SQLAlchemy Model 或 Repository 实现；
- `app/application` 不再导入 FastAPI、SQLAlchemy 和具体外部客户端；
- `app/domain` 不依赖任何数据库或网络库；
- `app/infrastructure` 是 SQLAlchemy、Milvus、MinIO、Embedding、LLM 的唯一具体实现位置；
- Repository 不自行创建 session、不自行 commit；
- `models/queries.py` 已删除，查询职责由业务 Repository 承担；
- `schemas.py` 按业务拆分；
- 文档入库仍然支持 Web 上传和 CLI 批量导入；
- 文档状态机、补偿删除、失败重试和启动恢复行为不变；
- API 契约和前端现有测试全部通过；
- 后端全量测试通过，并补充 Repository、Unit of Work 和核心 Application Service 测试；
- 使用静态搜索确认不存在新的绕层依赖。

建议最终执行以下检查：

```powershell
rg -n "from app\.db|from app\.models|from sqlalchemy|pymilvus|minio" backend/app/api backend/app/application backend/app/domain
rg -n "from fastapi|HTTPException" backend/app/application backend/app/domain
rg -n "get_async_session|AsyncSessionLocal|\.commit\(" backend/app/application backend/app/domain
```

这些命令的结果应只出现允许的基础设施和 API 位置。

## 13. 最终决策摘要

本项目采用以下后端架构决策：

1. 使用业务型 Repository，不使用通用 CRUD Repository。
2. 使用 Unit of Work 统一 MySQL 事务边界。
3. SQLAlchemy Model 和 Repository 实现在 `infrastructure` 内部。
4. Application Service 负责业务流程，Domain 负责稳定业务规则。
5. Milvus、MinIO、Embedding、LLM 使用 Port/Adapter，不归入 SQL Repository。
6. 保留文档状态机和跨系统补偿机制，不假设分布式原子事务。
7. 以 API 契约和现有业务行为不变为迁移约束。
8. 先建立边界和接口，再按业务模块逐步迁移，最后删除旧查询层。
