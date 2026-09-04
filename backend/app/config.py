"""全局配置。所有环境相关参数集中在此，通过 .env 覆盖。

内网服务端点均为 2026-09-03 实测确认，详见 docs/环境验证报告.md
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务 ----------
    app_name: str = "KnowledgeBase API"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    # 前端开发服务器地址，用于 CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ---------- 存储 ----------
    data_dir: Path = BASE_DIR / "data"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    sqlite_path: Path = BASE_DIR / "data" / "kb.db"

    # ---------- LLM 抽象层（provider 热切换）----------
    # 取值：qwen(内网 vLLM 默认) / deepseek(公网) / deepseek_intra(内网自建)
    llm_provider: str = "qwen"
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

    # ---------- Embedding（内网 docmind-embed + BGE-M3）----------
    # 实测：dense 1024 维 + sparse 词权重；360 条/秒；单批上限 256
    embed_base_url: str = "http://192.168.124.221:8003"
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024
    embed_batch_size: int = 64
    embed_max_batch: int = 256
    embed_timeout: float = 120.0

    # ---------- Milvus ----------
    milvus_host: str = "192.168.124.221"
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

    # ---------- 检索与生成 ----------
    # 送进大模型的片段数量（从 top_k 中取分数最高的若干条）
    rerank_top_n: int = 5
    score_threshold: float = 0.0
    max_context_tokens: int = 4000

    # ---------- 分块 ----------
    chunk_size: int = 512
    chunk_overlap: int = 64
    # 表格整体保留，不参与切分
    keep_table_intact: bool = True

    # ---------- 并发控制（1-5 人部门级）----------
    max_concurrent_requests: int = 3

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
