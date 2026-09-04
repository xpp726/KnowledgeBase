# 项目长期记忆：Xpp 知识库系统

## 项目定位
内网企业级知识库 RAG 问答系统。Vue3 前端 + Python FastAPI 后端，前后端分离。
规模目标 1000-10000 篇混合类型文档，1-5 人部门级使用，无需登录鉴权。

## 基础设施决策（2026-09-04 更新，用户拍板）
**LLM**：内网服务器 `192.168.124.221:8000/v1` 的 Qwen3-27B 保持不变（生产），
另开 **DeepSeek 适配口**（`deepseek-chat` 公网 API，开发期调试/备选），`LLM_PROVIDER` 一键切换。
**Embedding**：**本机 Docker 自建** BGE-M3（dense+sparse 双输出），不再依赖内网 8003。
**Milvus**：**本机 Docker 自建** standalone v2.5.27，新建 collection `kb_chunks`，不复用内网 372 万向量的 docmind 实例。

### 内网 LLM（`192.168.124.221:8000/v1`，仅此服务保留使用）
- 模型 `Qwen3.8-27B-FP8`（27B），vLLM 0.28.0，上下文 128K
- 生成 **21.3 tok/s**；真实首字延迟 **1.0-1.5s**；3 路并发无劣化
- ⚠️ 思考模式默认开启，必须传 `chat_template_kwargs: {"enable_thinking": false}`
- ⚠️ 无 embedding 接口，只有 chat/completions

### DeepSeek 公网 API（开发期）
- `https://api.deepseek.com`，模型 `deepseek-chat`（无思考）/`deepseek-reasoner`（有思考）
- 用户已配置 `DEEPSEEK_API_KEY` 环境变量，2026-09-04 实测流式+非流式均通

### 本机 Docker 基础设施（自建，部署文件在 `deploy/`）
- 本机：Docker Desktop 29.7.2 + Compose v5.4.0，**RTX 3060 Laptop 6GB**（GPU 透传已验证），68GB 内存
- 镜像版本（2026-09-04 实测确认，Docker Hub 官方直连源，已去掉加速器前缀）：
  - `milvusdb/milvus:v2.5.27`（dense+sparse 混合检索 + RRF；v2.5 LTS 最新 patch，含 2 个 critical CVE 修复）
  - `minio/minio:RELEASE.2023-12-20T01-00-02Z`（用新 env 名 `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`，旧 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` 已弃用）
  - `quay.io/coreos/etcd:v3.5.5`（quay.io 独立 registry 直连可用）
  - `zilliz/attu:v2.5`（可选可视化）
  - BGE-M3 自建 `kb-bge-m3:latest`（FlagEmbedding 1.3.3，唯一保证 dense+sparse 双输出的方案）
- BGE-M3 接口对齐内网 docmind-embed：`POST /embed` `{texts, return_dense, return_sparse, batch_size}`，dense 1024 维 + sparse `{token_id: weight}`，单批上限 256
- **BGE-M3 权重烘焙进镜像**（Dockerfile 构建期 `snapshot_download('BAAI/bge-m3')` → `/models/hub/`），目标机无需联网；构建机需可访问 `hf-mirror.com`（默认），可用 `--build-arg HF_ENDPOINT=...` 切换源；镜像大小 ~11 GB

### 不复用的服务
- `192.168.124.221:8003` docmind-embed（内网 GPU，仅作接口参考）
- `192.168.124.221:19530/9091` docmind 的 Milvus（有 372 万向量，勿动）
- `192.168.124.221:8001` docmind-index（其他项目，检索 280s 超时）

## 关键技术决策
- LLM 层**抽象层**（`backend/app/llm.py`）：qwen / deepseek / deepseek_intra 三 provider 热切换，差异只在 extra_body（Qwen 需关思考，DeepSeek 不需要）
- 混合检索 = BGE-M3 dense + sparse 双路 + RRF 融合，**省掉 Elasticsearch**
- **暂不引入 PaddleOCR** 和 Rerank，做成可插拔模块二期按需开启
- 响应指标：**首字 <1.5s + 流式**（21.3 tok/s 硬件约束，"5 秒完整答案"做不到）

## 样本文档（test_files/，真实数据）
- **国网电力系统招标/中标候选人公示**：7 个 PDF + 1 个 Excel
- 全部**文字版 PDF，无需 OCR** ✅；但 **48 页 / 37 个表格**（每页约 0.8 个），中标候选人/报价/排名全在表格里
- 表格单元格内大量碎片换行，需专门清洗规则；表格问答是核心场景，分块时表格整体保留不切

## 开发环境
- 本机 Windows 开发，Python 3.13.14（托管，venv 在 `~/.workbuddy/binaries/python/envs/kb`）/ Node v22.22.2
- ⚠️ pip 装包要加 `--no-cache-dir --no-clean`（沙箱删除保护会中断 pip 清理）
- 最终部署 Linux 服务器（信息待用户提供）

## 约定
- 文档 `docs/`，后端 `backend/`，前端 `frontend/`，部署 `deploy/`，评测 `eval/`
- 全程 `pathlib` + 显式 UTF-8
