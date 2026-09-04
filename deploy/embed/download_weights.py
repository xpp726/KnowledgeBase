"""
build-time 脚本：把 BAAI/bge-m3 完整权重烘焙到镜像内 /models/hub
由 deploy/embed/Dockerfile 在构建阶段调用
"""
import os
import sys

from huggingface_hub import snapshot_download


def main() -> int:
    repo_id = os.environ["MODEL_NAME"]
    hf_home = os.environ["HF_HOME"]
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    cache_dir = os.path.join(hf_home, "hub")

    allow_patterns = [
        "*.json",
        "*.txt",
        "*.model",
        "*.safetensors",
        "*.bin",
        "*.py",
        "tokenizer*",
        "vocab*",
        "sentencepiece*",
        "special_tokens*",
    ]

    print(f"[bake-weights] repo_id   = {repo_id}")
    print(f"[bake-weights] endpoint  = {endpoint}")
    print(f"[bake-weights] cache_dir = {cache_dir}")

    snapshot_download(
        repo_id=repo_id,
        cache_dir=cache_dir,
        endpoint=endpoint,
        allow_patterns=allow_patterns,
    )

    print("BGE-M3 权重烘焙完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
