# 项目长期记忆：Xpp 知识库系统

## 项目定位
内网企业级知识库 RAG 问答系统。Vue3 前端 + Python FastAPI 后端，前后端分离。
规模目标 1000-10000 篇混合类型文档，1-5 人部门级使用，无需登录鉴权（但已实现 JWT 可选项）。

## 技术栈（已落地，2026-09-08 核对实际代码）
- **前端**：Vue 3.5 + Vite 8 + TypeScript + Pinia 4 + Vue Router 5 + Element Plus 2.14
  + ECharts 6（vue-echarts 8）+ markdown-it + highlight.js（回答渲染）
  - 包管理器：**npm**（已确认，不要用 pnpm/yarn）
  - 启动：`npm run dev`（端口 5173）；代理 `/api` → `http://127.0.0.1:8000`
  - 构建：`npm run build` → `frontend/dist/`
- **后端**：FastAPI + uvicorn[standard] + Pydantic v2 + pydantic-settings
  - 启动入口：`python -m app.run`（不要用 `uvicorn app.main:app`，否则日志配置不生效）
    - 开发：`python -m app.run --reload`（Windows 下 reload 依赖交互控制台）
    - 端口：8000（config.PORT）
  - 数据层：SQLAlchemy 2.0 async + Alembic 迁移；`DATABASE_URL` 留空即用 SQLite（aiosqlite），
    填 `mysql+asyncmy://...` 即切 MySQL
  - **当前已切 MySQL 9.x（Docker kb-mysql）**：`DATABASE_URL=mysql+asyncmy://kb:***@127.0.0.1:13306/kb`
    - 宿主端口是 **13306 不是 3306**：本机 MySQL84 服务（开机自启）占用 3306，容器内仍是 3306
    - MySQL 9.x 已移除 `mysql_native_password`，只能 `caching_sha2_password`；asyncmy 0.2.14
      （有 cp313 轮子）+ cryptography 已实测可非 TLS 直连，**不要**加 `default-authentication-plugin` 参数（会启不来）
  - 对象存储：MinIO（s3）；**当前 `STORAGE_BACKEND=minio`**（2026-09-08 切，与部署环境一致），
    `MINIO_ENDPOINT=127.0.0.1:9000`、桶 `kb-files`（MinioStorage 构造时自动 `_ensure_bucket` 建桶）
  - 检索：pymilvus（collection `kb_chunks`，dense FLOAT_VECTOR 1024 + sparse SPARSE_FLOAT_VECTOR）
    + BGE-M3 Embedding（dense 1024 + sparse）
  - 文档解析：pymupdf4llm（PDF 含扫描件 OCR via RapidOCR）/ python-docx / openpyxl / python-pptx
    / beautifulsoup4 / lxml
  - 认证：python-jose(JWT) + bcrypt（已实现但默认不强制）
- **基础设施（本机 Docker）**：Milvus v2.5.27 standalone + MinIO + etcd + BGE-M3 + Attu
  （详见 `deploy/部署说明.md`、`deploy/离线部署/镜像打包与分发.md`）

## 关键约定
- 文档 `docs/`、后端 `backend/`、前端 `frontend/`、部署 `deploy/`、评测 `eval/`、样本 `test_files/`
- **默认知识库 + 默认 folder**：默认 kb `default_kb_id=default` / `default_kb_name=默认知识库`，
  默认 folder `default_kb_folder_name=默认文件夹`。`main.py` lifespan 同时调
  `ensure_default_knowledge_base()` + `ensure_default_folder()` **无则创建**（幂等）。
  默认 folder `is_system=True`：禁止删除、禁止移动，可改名。
- **Folder 树状组织（kb 维度，2026-09-08 阶段 4 落地）**：kb 顶级下挂 folder 树（最深 2 层）。
  - 同层 folder 名联合唯一 `(kb_id, parent_id, name)`；parent_id IS NULL 视为同一组
  - 同 folder 内 file_name 唯一 → **同名直接拒绝**（不静默覆盖；重新入库走 `POST /documents/{id}/reprocess`）
  - **doc_id 算法**：`md5(f"{kb_id}/{folder_id or ''}/{file_name}")[:16]`（含 folder 上下文，跨 folder 同名独立 doc_id）
  - folder **不参与 RAG 检索**（仍是 kb 级检索 + folder_path 溯源展示）
- **Milvus 集合**：kb_chunks 由入库流程创建，启动不建；documents.folder_id 不影响向量字段。
- LLM 抽象层：qwen（内网 vLLM）/ deepseek（公网）/ deepseek_intra（内网自部署）三 provider 热切换
  - **当前开发期 `LLM_PROVIDER=qwen`**（2026-09-07：服务器 Qwen `192.168.124.221:8000` 实测可达，
    `/v1/models` 返回 `Qwen3.8-27B-FP8`，与 `LLM_MODEL` 一致）；回公网开发再改 `deepseek` 并填 `DEEPSEEK_API_KEY`
  - 内网 Qwen3-27B-FP8 必须 `LLM_ENABLE_THINKING=false`（反之思考模式默认开）
- Embedding：`EMBED_BASE_URL=http://127.0.0.1:8003`（本机 Docker BGE-M3，**已用 127.0.0.1 而非 localhost
  以绕开 Windows `localhost→::1`(IPv6) 命中 Docker Desktop `wslrelay.exe` 转发链导致的 WinError 10053**）
  + `EMBED_MAX_BATCH=64`（256 太大易超时）/ `EMBED_TIMEOUT=300`（120 太短）/ `EMBED_MAX_RETRIES=2` 指数退避
- Milvus：`milvus_host=localhost`（仍用 localhost，gRPC 走 19530；若连不上改成 `127.0.0.1` 试）
  ；内网 221:19530 的 docmind 实例有 372 万向量且状态不健康，**勿连**
- MinIO：`minio_endpoint=127.0.0.1:9000`（**已改 127.0.0.1**，避开 localhost→IPv6 坑；桶 kb-files）

## 环境坑（Windows 本机）
- ⚠️ `requirements.txt` 里的 **asyncmy** 是 C 扩展，本机无 VS Build Tools 时编译失败会中断整个
  `pip install`。**开发期（用 SQLite）安装时剔除 asyncmy**（用临时 requirements 过滤该行），
  `requirements.txt` 保留它作为生产 MySQL 依赖真相源；生产部署需装 Visual C++ 生成工具或环境有 asyncmy 轮子。
- pip 装包的 `--no-cache-dir` 在 **WorkBuddy 沙箱**里是**必需**：沙箱的 `sitecustomize.py` 给 `os.remove`
  挂了批量删除守卫，pip 清理 HTTP 缓存时 `os.remove` 触发守卫 → `SystemExit(1)` 中止安装。
  本机 PowerShell 跑建议也加 `--no-cache-dir` 以防万一（`--no-clean` 不需要）。
- Node 22.x + Python 3.11+ 已验证可用（后端 venv 现用 WorkBuddy 管理的 **Python 3.13.12/实际 3.13.14**）。
- ⚠️ **onnxruntime 与 Anaconda 旧运行库冲突 —— 已用彻底方案根治（2026-09-07 执行方案 B）**：
  - 根因：原 `.venv` 基解释器是 **`D:\Anaconda3` 的 Python 3.12.4**，自带旧版
    `MSVCP140.dll v14.29.30153.0`（VS2019），DLL 搜索顺序优先级最高，盖过系统新版本。
  - 后果：onnxruntime ≥1.18（VS2022 编译）导入时 `0xc0000005` → `WinError 1114`，`import pymupdf4llm` 崩溃；
    1.17.3 太旧又不支持 pymupdf 1.28.2 的 ONNX IR10 模型（max supported IR version: 9）。
  - **已落地彻底方案**：后端 `.venv` 已重建于独立 Python
    `C:\Users\64817\.workbuddy\binaries\python\versions\3.13.12\python.exe`（自带 `vcruntime140 v14.44`），
    旧 Anaconda venv 改名备份为 `backend/.venv.anaconda.bak`。`requirements.txt` 锁 `onnxruntime==1.29.0`
    （1.20.1 无 cp313 轮子会在 3.13 下编译失败，必须升），验证 `onnxruntime 1.29.0 + numpy 2.5.2 + pymupdf4llm 1.28.2` 全 OK。
  - Anaconda 旧 venv 备份可手动删除：`backend/.venv.anaconda.bak`（批量删除守卫会拦截，需在资源管理器或
    先重启释放句柄后删除）。
- pip 阿里云镜像偶发 `flatbuffers` 等小轮子缓存损坏（`IncompleteRead`）→ 用
  `pip install --no-cache-dir --retries 10` 绕过。

## 测试与验收（改完代码必须跑，2026-09-08 全绿基线 154+59）
- **前端**：`cd frontend && npm test`（= `vitest run`，非 watch）；`npm run test:watch` 可监听。
  - 9 个测试文件 / **59 个用例**，全绿基线（folder 改造后 document.test.ts 增至 9 个）。
  - `npm run build`（`vue-tsc -b` + `vite build`）现已通过；此前因 `vitest` 未装导致测试文件
    报 `Cannot find module 'vitest'` 而失败，属环境缺失，非代码问题。
- **后端**：`cd backend && .venv\Scripts\python.exe -m pytest -q`
  - 14 个测试文件 / **154 passed** 基线（folder 改造后新增 23 个 test_folder_service.py 用例）。
- **验收顺序**：改代码 → 跑对应端测试 → 前端还需 `npm run build` 确认类型无误 → 再交付。
- 注意：改前端 `types/api.ts` 契约时，同步改 `src/stores/__tests__/*.test.ts` 的 mock/断言，
  否则 `vue-tsc` 会报 TS2353/TS2339。
- **后端测试与开发者 `.env` 解耦**：`tests/conftest.py` 强制 `DATABASE_URL` 指向独立 SQLite 测试库，
  并用 session 级 autouse fixture 执行 `create_all()` + `ensure_default_admin()`。
  切勿让测试连开发者本机 MySQL——asyncmy 在 Windows ProactorEventLoop 下跨事件循环复用连接会抛
  `AttributeError: 'NoneType' object has no attribute 'send'`，且结果会受本机开发数据影响。
- **启动迁移（`ensure_schema_patches`）**：SQLite 用 `pragma_table_info`，MySQL 用
  `information_schema.columns` 检测缺列；统一分支处理。文档 `documents.folder_id` 列是后加的，
  老 MySQL 部署启动时会自动 `ALTER TABLE` 加列（幂等）。

## ORM 约定（MySQL 兼容性）
- MySQL 的 VARCHAR **必须指定长度**。`Mapped[str]` 已在 `app/models/base.py` 通过
  `type_annotation_map = {str: String(255)}` 统一兜底，新增模型无需手写长度。
- 内容长度不可控的字段**必须**显式覆盖为 `Text` 或 `LongText`
  （`LongText = Text().with_variant(LONGTEXT, "mysql")`），否则会被截成 255 字符。
- 自查手段（不用连库）：`CreateTable(t).compile(dialect=mysql.dialect())` 逐表编译，
  能编译通过即 MySQL 可建表。
- **FK 命名约定**：`ForeignKey("folders.folder_id", ondelete="SET NULL")`——folder 删除时
  文档的 folder_id 自动置 NULL（不级联删除文档本身，文档删除走 `/documents/{id}` 接口单独处理）。

## 已生成文档
- `docs/开发计划.md` — 5 阶段开发计划
- `docs/环境安装.md` — 前后端 Windows 本机环境搭建（npm + venv）
- `deploy/部署说明.md` — Docker 基础设施启动与 profiles
- `deploy/离线部署/镜像打包与分发.md` + `images/导出全部镜像.ps1` — 内网镜像导出