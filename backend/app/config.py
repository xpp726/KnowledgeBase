"""全局配置。所有环境相关参数集中在此，通过 .env 覆盖。

设计说明：
- 采用扁平字段（不嵌套子模型），保证现有 .env（LLM_BASE_URL / MILVUS_HOST 等）零改动兼容。
- 字段按逻辑分区注释，便于维护。
- 数据库通过 database_url 切换方言：开发期 sqlite+aiosqlite，部署期 mysql+asyncmy。

内网服务端点 2026-09-03 实测见 docs/开发计划.md §二；2026-09-05 起开发环境切本机 Docker，见各字段注释。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==================== 服务 ====================
    app_name: str = "KnowledgeBase API"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    # 前端开发服务器地址，用于 CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ==================== 存储路径 ====================
    data_dir: Path = BASE_DIR / "data"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    # 旧裸 SQL 层使用的 SQLite 路径（过渡期保留，新代码用 database_url）
    sqlite_path: Path = BASE_DIR / "data" / "kb.db"

    # ==================== 日志持久化 ====================
    # 日志目录。相对路径以 backend 根目录 BASE_DIR 解析；可用 .env 的 LOG_DIR 覆盖（绝对/相对均可）
    log_dir: Path = BASE_DIR / "data" / "logs"
    # 日志级别：DEBUG / INFO / WARNING / ERROR
    log_level: str = "INFO"
    # 按天轮转（when=midnight），backupCount = 保留天数（超期文件自动删除）
    log_retention_days: int = 30

    @model_validator(mode="after")
    def _resolve_log_dir(self) -> "Settings":
        """log_dir 若为相对路径，统一以 BASE_DIR 为基准解析，避免依赖启动时的工作目录。"""
        if not Path(self.log_dir).is_absolute():
            self.log_dir = (BASE_DIR / self.log_dir).resolve()
        return self

    # ==================== 数据库（SQLAlchemy 2.0 async） ====================
    # 开发期：sqlite+aiosqlite；部署期：mysql+asyncmy://user:pass@host:3306/kb
    database_url: str = ""
    # 是否打印 SQL 语句（排障时临时开，默认关，避免与 debug 绑定导致日志爆炸）
    db_echo: bool = False

    # ==================== LLM 抽象层（provider 热切换） ====================
    # 取值：qwen(内网 vLLM 生产) / deepseek(公网) / deepseek_intra(内网自建)
    # 2026-09-05：内网 221 开发机不可达（ping 全丢），开发期切 deepseek；
    # 回到内网环境后改回 qwen 即可，抽象层已支持热切换，无需改业务代码。
    llm_provider: str = "deepseek"
    llm_timeout: float = 300.0
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.3

    # --- qwen：内网 vLLM（Qwen3-27B-FP8）---
    # 实测：21.3 tok/s，首字延迟 1.0-1.5s
    llm_base_url: str = "http://192.168.124.221:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "Qwen3.8-27B-FP8"
    # 实测：思考模式默认开启，不关闭会白白多耗 1-2 秒
    llm_enable_thinking: bool = False

    # --- deepseek：公网官方 API ---
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    # deepseek-chat 无思考；deepseek-reasoner 带思考（更慢更强）
    deepseek_model: str = "deepseek-chat"

    # --- deepseek_intra：内网自部署 DeepSeek（OpenAI 兼容）---
    deepseek_intra_base_url: str = ""
    deepseek_intra_api_key: str = "EMPTY"
    deepseek_intra_model: str = "deepseek-chat"

    # ==================== Embedding（本机 Docker 自建 BGE-M3） ====================
    # 2026-09-05 实测：dense 1024 维 + sparse 18 个非零项；
    # 首次调用 40.3s（模型懒加载 + CUDA 初始化），热态 0.285s
    # ⚠️ 内网 221:8003 的 docmind-embed 已弃用，勿再指向它
    embed_base_url: str = "http://localhost:8003"
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024
    # 单批 256 是 BGE-M3 服务硬限（实测大文档入库时 256 chunk × 500 字符 推理 > 120s，
    # 客户端 timeout 直接吃掉整批）。降到 64 让单批推理时长可预测（典型 < 30s）。
    embed_batch_size: int = 64
    embed_max_batch: int = 64
    # 客户端 timeout 必须远大于"最坏单批推理时长"。
    # 设备监控 40 号（364 chunk，拆 6 批 × ~40s）实测首字 50s、整批 ~80s。
    # 留 5 分钟给 GPU 抢占 / 大模型首次缓存 miss 等极端场景。
    embed_timeout: float = 300.0
    # 单批推理失败时重试次数（指数退避），用于应对 GPU 抢占 / 服务瞬断等临时故障。
    embed_max_retries: int = 2
    embed_retry_base_delay: float = 2.0

    # ==================== Milvus（本机 Docker 自建 standalone v2.5.27） ====================
    # ⚠️ 内网 221:19530 的 docmind 实例有 372 万向量且状态不健康，勿连
    milvus_host: str = "localhost"
    milvus_port: str = "19530"
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_collection: str = "kb_chunks"
    # 混合检索：dense 与 sparse 两路召回后 RRF 融合
    milvus_top_k: int = 30
    milvus_rrf_k: int = 60
    milvus_dense_weight: float = 1.0
    milvus_sparse_weight: float = 1.0
    milvus_search_timeout: float = 30.0

    # ==================== 文件存储（原始文档） ====================
    # 后端选择：local（开发期写本地 upload_dir）/ minio（部署期对象存储）
    storage_backend: str = "local"

    # MinIO：deploy/docker-compose.yml 中已运行（Milvus 依赖），业务文件复用同一实例、独立 bucket
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "kb-files"
    minio_secure: bool = False

    # ==================== 多知识库 ====================
    # 首次启动自动创建的默认知识库（所有未指定 kb 的文档归入此库）
    default_kb_name: str = "默认知识库"
    default_kb_id: str = "default"

    # ==================== 检索与生成 ====================
    # 送进大模型的片段数量（从 top_k 中取分数最高的若干条）
    rerank_top_n: int = 5
    # dense 相似度下限（COSINE，BGE-M3）。低于此值视为知识库无相关内容，
    # 直接回固定话术、不调用 LLM，防止小语料下"任何问题都召回 top-k"导致幻觉。
    # 0.55 由 scripts/_probe_threshold.py 在当前语料标定：相关问题 top1≥0.644，
    # 无关问题 top1≤0.509，0.55 落在干净分界区间；语料大幅扩充后应重新标定，可用 SCORE_THRESHOLD 覆盖。
    score_threshold: float = 0.55
    max_context_tokens: int = 4000

    # ==================== 分块 ====================
    chunk_size: int = 512
    chunk_overlap: int = 64
    # 表格整体保留，不参与切分
    keep_table_intact: bool = True

    # ==================== PDF OCR 兜底（扫描件 PDF） ====================
    # 文字型 PDF 走 pymupdf4llm（保留表格）；扫描件（无文本层）自动 fallback 到 OCR。
    # 经验根因：2026-09-08 专项成本任务书 PDF 是 19 页扫描件，每页只有 1 张 JPEG 图，
    # get_text() 返回空 → 解析报"0 页"失败。这是"早期 7 个文字型 PDF 实测无需 OCR"的
    # 数据假设偏差造成的，遇到第一个扫描件就崩。
    # 默认开：保持"传什么都能入库"的契约。关闭（false）用于排障或性能调优。
    pdf_ocr_enabled: bool = True
    # OCR 渲染 DPI：200 在中文印刷体识别率与速度间平衡（200 DPI ≈ 1657×2332 px/A4）。
    # 提高到 300 会显著变慢但准确率提升有限；降到 150 会丢小字。
    pdf_ocr_dpi: int = 200
    # 单页 OCR 超时（秒）。RapidOCR 偶尔在某页卡住（罕见但发生过），需要硬上限。
    pdf_ocr_page_timeout: float = 60.0

    # ==================== 并发控制（5-10 人部门级，单进程） ====================
    max_concurrent_requests: int = 3
    # 文档解析/向量化并发上限：embedding 与 Milvus 是瓶颈，限制同时处理的文档数，
    # 其余上传排 pending 等待调度（多文件上传时防止打爆外部服务）
    max_concurrent_ingest: int = 2

    # ==================== 上传限制 ====================
    # 单文件大小上限（MB），超过返回 413
    upload_max_mb: int = 50

    # ==================== 后台任务 / 状态恢复 ====================
    # 文档停在 pending/ingesting/embedding 超过该秒数即判定为进程中断卡死，
    # 启动时扫描并标记 failed，可再触发重试（步骤6 状态机）
    stuck_timeout_seconds: int = 1800

    # ==================== 认证与权限 ====================
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    default_admin_username: str = "admin"
    default_admin_password: str = "admin"
    default_admin_display_name: str = "系统管理员"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def resolved_database_url(self) -> str:
        """返回实际使用的数据库连接串。

        未配置 database_url 时，默认指向开发期 SQLite（与 sqlite_path 同文件），
        保证开箱即用；部署期在 .env 中设置 DATABASE_URL 即可切换 MySQL。
        """
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.sqlite_path.resolve().as_posix()}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
