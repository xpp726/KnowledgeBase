"""系统设置 service 测试：.env 写回原子性与保留注释、参数校验、白名单与掩码、API 透传。

用 monkeypatch 把 ENV_PATH / CONFIG_FILE 指向临时文件，避免污染真实 .env / 触发真实 reload。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.config_api import router
from app.main import app as main_app
from app.services import config_service as cs

ENV_HEADER = """# 复制为 .env 后按需修改
# 服务
APP_NAME=KnowledgeBase API
PORT=8000

# 检索与生成
RERANK_TOP_N=5
SCORE_THRESHOLD=0.55
CHUNK_SIZE=512
"""


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """把 .env 指向临时文件，并屏蔽自动重启（避免测试内真实 spawn / os._exit）。"""
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_HEADER, encoding="utf-8")
    monkeypatch.setattr(cs, "ENV_PATH", env_file)
    monkeypatch.setattr(cs, "_schedule_restart", lambda: True)
    return env_file


# ---------------- .env 写回 ----------------

def test_write_env_replace_and_keep_comment(isolated):
    env_file = isolated
    text = cs._read_env_text()
    text = cs._write_env_key(text, "SCORE_THRESHOLD", "0.60")
    text = cs._write_env_key(text, "UPLOAD_MAX_MB", "100")  # 不存在 → 追加
    cs._atomic_write(text)
    content = env_file.read_text(encoding="utf-8")
    # 注释与无关行保留
    assert "# 检索与生成" in content
    assert "APP_NAME=KnowledgeBase API" in content
    # 替换生效
    assert "SCORE_THRESHOLD=0.60" in content
    assert "SCORE_THRESHOLD=0.55" not in content
    # 追加生效
    assert "UPLOAD_MAX_MB=100" in content


def test_save_params_updates_env_and_returns(isolated):
    env_file = isolated
    r = cs.save_params({"score_threshold": 0.6, "rerank_top_n": 6, "log_level": "WARNING"})
    assert r["saved"] == ["score_threshold", "rerank_top_n", "log_level"]
    assert r["needs_restart"] is False  # spawn 成功 → 自动重启
    content = env_file.read_text(encoding="utf-8")
    assert "SCORE_THRESHOLD=0.6" in content
    assert "RERANK_TOP_N=6" in content
    assert "LOG_LEVEL=WARNING" in content
    assert "CHUNK_SIZE=512" in content  # 无关行保留


def test_save_params_unknown_key_rejected(isolated):
    with pytest.raises(ValueError, match="不可编辑"):
        cs.save_params({"llm_provider": "qwen"})


def test_save_params_range_rejected(isolated):
    with pytest.raises(ValueError, match="0.1 ~ 0.95"):
        cs.save_params({"score_threshold": 2.0})
    with pytest.raises(ValueError, match="必须是数字"):
        cs.save_params({"rerank_top_n": "abc"})
    with pytest.raises(ValueError, match="取值需为"):
        cs.save_params({"log_level": "VERBOSE"})


def test_schedule_restart_spawn_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("spawn failed")

    monkeypatch.setattr(cs.subprocess, "Popen", boom)
    assert cs._schedule_restart() is False


# ---------------- 白名单与掩码 ----------------

def test_params_snapshot_editable_and_mask():
    s = cs.get_params_snapshot(cs.get_settings())
    editable_keys = [i["key"] for i in s["editable"]]
    assert len(editable_keys) == 10
    assert "score_threshold" in editable_keys and "log_retention_days" in editable_keys
    # 基础设施只读
    infra = {i["key"]: i for i in s["infra"]}
    assert "llm_provider" in infra and "milvus" in infra
    # 敏感掩码
    for k in ("llm_api_key", "deepseek_api_key", "minio_secret_key"):
        v = infra[k]["value"]
        assert v in ("未配置", "****") or ("****" in v)


def test_mask():
    assert cs._mask("") == "未配置"
    assert cs._mask("EMPTY") == "未配置"
    assert cs._mask("short") == "****"
    assert cs._mask("sk-abcdef1234567890").startswith("sk-a")
    assert cs._mask("sk-abcdef1234567890").endswith("7890")


def test_system_info_shape():
    info = cs.get_system_info(cs.get_settings())
    for k in ("app_name", "version", "database", "llm_provider", "log_dir", "reload_mode"):
        assert k in info


# ---------------- API 透传 ----------------

def _admin_token(client: TestClient) -> str:
    """用默认 admin 登录获取 token（确保 users 表有 admin）。"""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    if r.status_code != 200:
        # 某些测试库可能无 admin，直接构造一个测试 token（jwt_secret 默认值）
        from app.services.auth import create_access_token, User
        u = User(id="u_admin", username="admin", role="admin", is_active=True)
        return create_access_token(u)
    return r.json()["token"]


def test_config_api_routes():
    client = TestClient(main_app)
    token = _admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/config/system", headers=headers).status_code == 200
    assert client.get("/api/config/params", headers=headers).status_code == 200
    assert client.get("/api/config/diagnostics", headers=headers).status_code == 200


def test_config_save_validation_api(isolated):
    client = TestClient(main_app)
    token = _admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.put("/api/config/params", json={"score_threshold": 9.9}, headers=headers)
    assert r.status_code == 422
    assert "0.1 ~ 0.95" in r.json()["detail"]
