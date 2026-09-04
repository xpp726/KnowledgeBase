# BGE-M3 向量化服务（dense 1024 维 + sparse 词权重）
#
# 构建：docker build -t kb-bge-m3:latest ./embed
# 运行：见 deploy/docker-compose.yml
#
# 镜像内容：CUDA runtime + PyTorch + FlagEmbedding + BGE-M3 完整权重（烘焙）
# 构建机要求：能联网（首次构建下载 ~2.2 GB 权重）。
#             通过 --build-arg HF_ENDPOINT=... 可切换 HuggingFace 镜像源。
# 目标机要求：完全离线可用。无需现场下载。

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    MODEL_NAME=BAAI/bge-m3 \
    MAX_TEXTS=256 \
    DEFAULT_BATCH=32 \
    USE_FP16=true \
    # 烘焙的权重已在镜像内，禁止 huggingface_hub / transformers 任何联网校验。
    # 否则镜像里没有的隐藏文件（如 imgs/.DS_Store）会让 hf-mirror 返回 403。
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# ---- apt 源与重试（均可在构建时覆盖）----
# 坑：archive.ubuntu.com 主站在镜像同步期间会自相矛盾——Release 文件里记录的大小
# 与实际下发的 Packages.gz 对不上（实测 Release 记 4622598，实际 4622604），
# apt 直接 exit 100，报 "File has unexpected size ... Mirror sync in progress?"。
# 国内镜像已完成同步且 Release 与实际文件自校验一致（实测均为 4622604），换源即可绕过。
# 若需回退官方源：--build-arg APT_MIRROR=archive.ubuntu.com
ARG APT_MIRROR=mirrors.aliyun.com
ARG APT_RETRIES=5

# 同时兼容经典 sources.list 与 deb822 的 ubuntu.sources；CUDA 官方源不在替换范围，
# 保持 developer.download.nvidia.com 原样不动
RUN set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do \
        if [ -f "$f" ]; then \
            sed -i -e "s|http://archive\.ubuntu\.com|https://${APT_MIRROR}|g" \
                   -e "s|http://security\.ubuntu\.com|https://${APT_MIRROR}|g" "$f"; \
        fi; \
    done; \
    apt-get update \
        -o Acquire::Retries=${APT_RETRIES} \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30

RUN apt-get install -y --no-install-recommends \
        -o Acquire::Retries=${APT_RETRIES} \
        python3.10 python3-pip python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 国内网络加速：HuggingFace 镜像与 PyPI 源，构建时可覆盖
ARG HF_ENDPOINT=https://hf-mirror.com
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ENV HF_ENDPOINT=${HF_ENDPOINT}
ENV PIP_INDEX_URL=${PIP_INDEX}

# pip 默认 --timeout 只有 15 秒，下载 GB 级大包时一旦卡顿超过 15s 就会中断整个构建。
# 这里放大超时并加重试，避免网络抖动把构建打回原点。
ARG PIP_TIMEOUT=120
ARG PIP_RETRIES=10

RUN python3 -m pip install --upgrade pip \
        --timeout ${PIP_TIMEOUT} --retries ${PIP_RETRIES}

# PyTorch 2.6.0（PyPI 默认即 CUDA 12.4 版本，走清华源 PIP_INDEX_URL）
# 含 nvidia-* CUDA 依赖，合计约 4~5 GB，是整个构建最慢的一步
RUN python3 -m pip install torch==2.6.0 \
        --timeout ${PIP_TIMEOUT} --retries ${PIP_RETRIES}

RUN python3 -m pip install \
        --timeout ${PIP_TIMEOUT} --retries ${PIP_RETRIES} \
        fastapi==0.115.6 \
        "uvicorn[standard]==0.34.0" \
        FlagEmbedding==1.3.3 \
        huggingface_hub==0.27.0 \
        numpy==1.26.4

WORKDIR /app
COPY server.py /app/server.py
COPY download_weights.py /app/download_weights.py

# ============================================================
# 烘焙 BGE-M3 完整权重到 /models/hub（约 2.2 GB）
# 标准 HuggingFace cache 格式，FlagEmbedding 运行时自动复用
# 单独脚本 + COPY 进来，避免 RUN python3 -c "..." 多行写法触发 Dockerfile
# 解析器把 from ... 误判成 FROM 指令的问题
# ============================================================
RUN python3 /app/download_weights.py

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:8003/health')" || exit 1

CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8003"]