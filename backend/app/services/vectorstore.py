"""Milvus 向量库客户端（dense + sparse 混合检索 + RRF 融合）。

⚠️ API 选型：pymilvus 3.0 起官方弃用 `connections` / `utility` 这类 ORM 风格接口
（运行会打 PyMilvusDeprecationWarning，3.1 将移除），因此本模块统一使用新的
`MilvusClient` 客户端。

集合设计（kb_chunks）：
- `dense`  FLOAT_VECTOR(1024)        → BGE-M3 dense，HNSW + COSINE
- `sparse` SPARSE_FLOAT_VECTOR       → BGE-M3 词权重，SPARSE_INVERTED_INDEX + IP（Milvus 限制：稀疏向量只能用 IP）
- 检索时两路各召回 top_k，再用 RRF（Reciprocal Rank Fusion）融合，
  等效于"向量语义 + 关键词"双路召回，因此不需要额外部署 Elasticsearch。

实测（2026-09-05）：Milvus 服务端 v2.5.27，客户端 pymilvus 3.0.1，连接耗时 142ms，兼容无问题。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pymilvus import AnnSearchRequest, DataType, MilvusClient, RRFRanker

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorStoreError(RuntimeError):
    """向量库操作失败。"""


@dataclass
class Hit:
    """检索命中结果。"""

    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int
    score: float  # RRF 融合后的分数，越大越相关
    kb_id: str = "default"

    def __repr__(self) -> str:
        return f"<Hit {self.chunk_id} score={self.score:.4f} {self.doc_name[:30]}>"


# ---- 集合 schema 常量 ----
FIELD_CHUNK_ID = "chunk_id"
FIELD_KB_ID = "kb_id"
FIELD_DOC_ID = "doc_id"
FIELD_DOC_NAME = "doc_name"
FIELD_TEXT = "text"
FIELD_PAGE = "page"
FIELD_DENSE = "dense"
FIELD_SPARSE = "sparse"

OUTPUT_FIELDS = [
    FIELD_CHUNK_ID, FIELD_KB_ID, FIELD_DOC_ID, FIELD_DOC_NAME, FIELD_TEXT, FIELD_PAGE
]

TEXT_MAX_LENGTH = 16384
NAME_MAX_LENGTH = 512
ID_MAX_LENGTH = 64


class VectorStore:
    """Milvus 集合的建表、写入与混合检索封装。"""

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        collection: str | None = None,
    ) -> None:
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection = collection or settings.milvus_collection
        self.client = MilvusClient(uri=f"http://{self.host}:{self.port}")

    # ---------- 集合管理 ----------
    def has_collection(self) -> bool:
        return self.client.has_collection(self.collection)

    def ensure_collection(self, drop_if_exists: bool = False) -> None:
        """创建 kb_chunks 集合并建好双路索引。已存在则跳过。"""
        if self.has_collection():
            if drop_if_exists:
                logger.warning("删除已存在的集合 %s", self.collection)
                self.client.drop_collection(self.collection)
            else:
                logger.info("集合 %s 已存在，跳过创建", self.collection)
                return

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            FIELD_CHUNK_ID, DataType.VARCHAR, max_length=ID_MAX_LENGTH, is_primary=True
        )
        # 多知识库维度：所有检索按 kb_id 标量过滤，单 collection 承载多库
        schema.add_field(FIELD_KB_ID, DataType.VARCHAR, max_length=ID_MAX_LENGTH)
        schema.add_field(FIELD_DOC_ID, DataType.VARCHAR, max_length=ID_MAX_LENGTH)
        schema.add_field(FIELD_DOC_NAME, DataType.VARCHAR, max_length=NAME_MAX_LENGTH)
        schema.add_field(FIELD_TEXT, DataType.VARCHAR, max_length=TEXT_MAX_LENGTH)
        schema.add_field(FIELD_PAGE, DataType.INT64)
        schema.add_field(FIELD_DENSE, DataType.FLOAT_VECTOR, dim=settings.embed_dim)
        schema.add_field(FIELD_SPARSE, DataType.SPARSE_FLOAT_VECTOR)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name=FIELD_DENSE,
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name=FIELD_SPARSE,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        # kb_id 倒排标量索引，加速多知识库过滤
        index_params.add_index(field_name=FIELD_KB_ID, index_type="INVERTED")

        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("集合 %s 创建完成（dense HNSW + sparse inverted）", self.collection)

    def load(self) -> None:
        """加载到内存。检索前必须调用，否则查不到数据。"""
        self.client.load_collection(self.collection)

    def count(self) -> int:
        """返回逻辑行数（实时可查到的条数）。

        注意：get_collection_stats 的 row_count 是物理段统计，在
        delete+insert 后不会立即下降、会把墓碑记录也算进去，频繁删插场景
        会偏大（实测重入库后显示 2 倍）。因此这里走 count(*) 聚合，拿到
        的是与 query/检索一致的真实条数；query 要求集合 loaded，load 幂等。
        """
        if not self.has_collection():
            return 0
        try:
            self.client.load_collection(self.collection)
            res = self.client.query(
                self.collection,
                filter=f'{FIELD_CHUNK_ID} != ""',
                output_fields=["count(*)"],
            )
            if res:
                return int(res[0].get("count(*)", 0))
        except Exception as exc:  # 聚合不支持时回退物理统计，并明确告警
            logger.warning("count(*) 聚合失败，回退物理 row_count：%s", exc)
        return self.client.get_collection_stats(self.collection).get("row_count", 0)

    # ---------- 写入 ----------
    def insert(self, rows: list[dict[str, Any]], batch_size: int = 200) -> int:
        """批量写入。rows 每项需含 chunk_id/doc_id/doc_name/text/page/dense/sparse。"""
        if not rows:
            return 0

        written = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            # 文本超长会被 Milvus 截断报错，这里提前裁掉并告警
            for r in batch:
                if len(r.get(FIELD_TEXT, "")) > TEXT_MAX_LENGTH:
                    logger.warning(
                        "chunk %s 文本超长，已截断至 %d 字符",
                        r.get(FIELD_CHUNK_ID),
                        TEXT_MAX_LENGTH,
                    )
                    r[FIELD_TEXT] = r[FIELD_TEXT][:TEXT_MAX_LENGTH]
            self.client.insert(collection_name=self.collection, data=batch)
            written += len(batch)
            logger.debug("已写入 %d/%d 条", written, len(rows))

        self.client.flush(self.collection)
        return written

    def delete_by_doc(self, doc_id: str, kb_id: str | None = None) -> int:
        """按文档删除，用于重新解析或删除文档。kb_id 非空时叠加过滤，防跨库误删。

        集合不存在时（清库后/全新环境的首次入库）视为无旧数据可删，直接返回 0，
        不抛异常。否则"首次入库"会因为前置 delete 步骤而 100% 失败。
        """
        if not self.has_collection():
            return 0
        # 集合存在但可能处于未加载状态（如被 release / 清库后未重新加载），
        # Milvus 的 delete 要求集合已加载，否则重新入库的"先清旧向量"步骤会 100% 失败。
        # load 幂等，这里先确保 loaded 再删。
        self.load()
        filt = f'{FIELD_DOC_ID} == "{doc_id}"'
        if kb_id:
            filt += f' and {FIELD_KB_ID} == "{kb_id.replace(chr(34), "")}"'
        res = self.client.delete(
            collection_name=self.collection,
            filter=filt,
        )
        return res.get("delete_count", 0) if isinstance(res, dict) else 0

    # ---------- 检索 ----------
    @staticmethod
    def _kb_filter(kb_id: str | None) -> str | None:
        """构造 kb_id 标量过滤表达式。kb_id 为空表示跨库检索（不追加过滤）。"""
        if not kb_id:
            return None
        # 转义双引号，防止表达式注入
        safe = kb_id.replace('"', '')
        return f'{FIELD_KB_ID} == "{safe}"'

    def hybrid_search(
        self,
        dense: list[float],
        sparse: dict[int, float],
        top_k: int | None = None,
        kb_id: str | None = None,
    ) -> list[Hit]:
        """dense + sparse 双路召回，RRF 融合。kb_id 非空时只在该知识库内检索。"""
        top_k = top_k or settings.milvus_top_k
        # 检索前确保集合已加载（load 幂等），避免集合被卸载后检索失败
        self.load()
        expr = self._kb_filter(kb_id)

        req_dense = AnnSearchRequest(
            data=[dense],
            anns_field=FIELD_DENSE,
            param={"metric_type": "COSINE", "params": {"ef": max(64, top_k * 2)}},
            limit=top_k,
            expr=expr,
        )
        req_sparse = AnnSearchRequest(
            data=[sparse],
            anns_field=FIELD_SPARSE,
            param={"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
            limit=top_k,
            expr=expr,
        )

        rows = self.client.hybrid_search(
            collection_name=self.collection,
            reqs=[req_dense, req_sparse],
            ranker=RRFRanker(settings.milvus_rrf_k),
            limit=top_k,
            output_fields=OUTPUT_FIELDS,
        )

        return self._to_hits(rows)

    def dense_search(
        self, dense: list[float], top_k: int | None = None, kb_id: str | None = None
    ) -> list[Hit]:
        """仅向量召回，用于与混合检索做效果对比。"""
        top_k = top_k or settings.milvus_top_k
        # 检索前确保集合已加载（load 幂等），避免集合被卸载后检索失败
        self.load()
        rows = self.client.search(
            collection_name=self.collection,
            data=[dense],
            anns_field=FIELD_DENSE,
            search_params={"metric_type": "COSINE", "params": {"ef": max(64, top_k * 2)}},
            limit=top_k,
            filter=self._kb_filter(kb_id),
            output_fields=OUTPUT_FIELDS,
        )
        return self._to_hits(rows)

    def sparse_search(
        self,
        sparse: dict[int, float],
        top_k: int | None = None,
        kb_id: str | None = None,
    ) -> list[Hit]:
        """仅关键词（稀疏向量）召回，用于效果对比。"""
        top_k = top_k or settings.milvus_top_k
        # 检索前确保集合已加载（load 幂等），避免集合被卸载后检索失败
        self.load()
        rows = self.client.search(
            collection_name=self.collection,
            data=[sparse],
            anns_field=FIELD_SPARSE,
            search_params={"metric_type": "IP"},
            limit=top_k,
            filter=self._kb_filter(kb_id),
            output_fields=OUTPUT_FIELDS,
        )
        return self._to_hits(rows)

    @staticmethod
    def _to_hits(rows: Any) -> list[Hit]:
        """MilvusClient 返回形如 [[{id, distance, entity{...}}, ...]]，做一层扁平化。"""
        hits: list[Hit] = []
        if not rows:
            return hits
        for group in rows:
            for item in group:
                entity = item.get("entity", {})
                hits.append(
                    Hit(
                        chunk_id=entity.get(FIELD_CHUNK_ID, ""),
                        doc_id=entity.get(FIELD_DOC_ID, ""),
                        doc_name=entity.get(FIELD_DOC_NAME, ""),
                        text=entity.get(FIELD_TEXT, ""),
                        page=entity.get(FIELD_PAGE, 0),
                        score=float(item.get("distance", 0.0)),
                        kb_id=entity.get(FIELD_KB_ID, "default"),
                    )
                )
        return hits


_store: VectorStore | None = None


def get_vectorstore() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
