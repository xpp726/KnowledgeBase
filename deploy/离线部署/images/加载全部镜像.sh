#!/usr/bin/env bash
# 一键加载全部 KB 基础设施镜像
# 用法：bash 加载全部镜像.sh
# 要求：当前目录有 kb-bge-m3.tar.gz / milvus.tar.gz / etcd.tar.gz / minio.tar.gz / attu.tar.gz

set -e
cd "$(dirname "$0")"

images=(
    "kb-bge-m3.tar.gz"
    "milvus.tar.gz"
    "etcd.tar.gz"
    "minio.tar.gz"
    "attu.tar.gz"
)

for f in "${images[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "==> 缺少文件: $f（跳过）"
        continue
    fi
    echo "==> 加载 $f ..."
    gunzip -c "$f" | docker load
done

echo ""
echo "==> 加载完成。当前镜像列表："
docker images | grep -E "kb-bge-m3|milvus|attu|coreos/etcd|minio/minio" || echo "（未找到目标镜像，请检查）"

echo ""
echo "下一步："
echo "  cd <项目 deploy 目录>"
echo "  docker-compose --profile tools up -d"