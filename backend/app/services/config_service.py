"""系统设置 service：参数白名单、校验、写回 .env、触发自动重启、系统信息。

设计说明：
- 可编辑参数白名单 EDITABLE_PARAMS：只暴露有调参价值且安全的业务参数；
  基础设施参数（llm_provider / embed / milvus / minio 等）只读展示，敏感字段掩码。
- 保存 = 校验 → 原子写回 .env（保留注释与无关行）→ 延迟 spawn 新进程并退出自身，
  由新进程等待端口释放后启动（不依赖 uvicorn reload：Windows 无控制台后台进程下
  uvicorn 的 CTRL_C_EVENT 重启信号无法送达会挂起，见 run.py 的 _wait_port_free）。
- ENV_PATH / CONFIG_FILE 可注入（测试指向临时文件），避免污染真实 .env。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.config import BASE_DIR, Settings, get_settings

APP_VERSION = "0.3.0"
START_TIME = time.time()

# .env 路径（测试可 monkeypatch 指向临时文件）
ENV_PATH = BASE_DIR / ".env"

# 敏感字段（不回传明文，只回传是否已配置 + 掩码）
_SENSITIVE_KEYS = {
    "llm_api_key",
    "deepseek_api_key",
    "deepseek_intra_api_key",
    "minio_secret_key",
}

# 可编辑参数白名单：settings 字段名 -> 元信息（供前端渲染表单 + 后端校验）
# coerce: int / float / enum；label/desc 用于展示；min/max/step 用于 number 校验
EDITABLE_PARAMS: dict[str, dict] = {
    "score_threshold": {
        "label": "相似度阈值",
        "desc": "低于此相似度视为知识库无相关内容，不调用 LLM（语料扩充后需重新标定）",
        "type": "number", "coerce": "float", "min": 0.1, "max": 0.95, "step": 0.05,
    },
    "rerank_top_n": {
        "label": "送模型片段数",
        "desc": "从召回结果中取分数最高的 N 条拼进上下文送大模型",
        "type": "number", "coerce": "int", "min": 1, "max": 20, "step": 1,
    },
    "max_context_tokens": {
        "label": "最大上下文 Token",
        "desc": "拼进提示词的检索片段总 token 上限",
        "type": "number", "coerce": "int", "min": 500, "max": 16000, "step": 100,
    },
    "llm_temperature": {
        "label": "生成温度",
        "desc": "越低越确定（事实问答建议 0.1~0.5）",
        "type": "number", "coerce": "float", "min": 0.0, "max": 2.0, "step": 0.1,
    },
    "llm_max_tokens": {
        "label": "回答最大 Token",
        "desc": "单次回答的生成长度上限",
        "type": "number", "coerce": "int", "min": 64, "max": 8192, "step": 64,
    },
    "max_concurrent_requests": {
        "label": "问答并发数",
        "desc": "同时处理的问答请求上限（5-10 人部门级）",
        "type": "number", "coerce": "int", "min": 1, "max": 10, "step": 1,
    },
    "max_concurrent_ingest": {
        "label": "文档解析并发数",
        "desc": "同时解析/向量化的文档数，其余排队（embedding 与 Milvus 是瓶颈）",
        "type": "number", "coerce": "int", "min": 1, "max": 10, "step": 1,
    },
    "upload_max_mb": {
        "label": "单文件上传上限",
        "desc": "超过该大小的文件拒绝上传（MB）",
        "type": "number", "coerce": "int", "min": 1, "max": 500, "step": 1,
    },
    "log_level": {
        "label": "日志级别",
        "desc": "日志文件记录的级别（越靠下越精简）",
        "type": "select", "coerce": "enum",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "log_retention_days": {
        "label": "日志保留天数",
        "desc": "按天轮转，超期文件自动删除",
        "type": "number", "coerce": "int", "min": 1, "max": 365, "step": 1,
    },
}


def is_reload_mode() -> bool:
    """是否以 uvicorn --reload 模式运行（决定保存后能否自动重启生效）。"""
    return "--reload" in sys.argv


def _mask(value: str) -> str:
    """敏感字段掩码：未配置 / 前4后4。"""
    if not value or value in ("EMPTY", ""):
        return "未配置"
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def get_params_snapshot(settings: Settings) -> dict:
    """可编辑白名单当前值 + 基础设施只读展示。"""
    editable = [
        {"key": key, "value": getattr(settings, key), **meta}
        for key, meta in EDITABLE_PARAMS.items()
    ]
    infra = [
        {"key": "llm_provider", "label": "LLM 供应商", "value": f"{settings.llm_provider} / {settings.llm_model}"},
        {"key": "llm_base_url", "label": "LLM 服务地址", "value": settings.llm_base_url},
        {"key": "deepseek_base_url", "label": "DeepSeek 地址", "value": settings.deepseek_base_url or "未配置"},
        {"key": "embedding", "label": "Embedding 服务", "value": f"{settings.embed_base_url} / {settings.embed_model}"},
        {"key": "milvus", "label": "Milvus", "value": f"{settings.milvus_host}:{settings.milvus_port} / {settings.milvus_collection}"},
        {"key": "storage_backend", "label": "文件存储", "value": f"{settings.storage_backend}（{settings.minio_endpoint or '本地目录'}）"},
        {"key": "database", "label": "数据库", "value": "sqlite" if "sqlite" in settings.resolved_database_url else settings.resolved_database_url},
        {"key": "default_kb", "label": "默认知识库", "value": f"{settings.default_kb_name}（{settings.default_kb_id}）"},
        {"key": "chunk", "label": "分块策略", "value": f"size={settings.chunk_size} overlap={settings.chunk_overlap} keep_table={settings.keep_table_intact}"},
        {"key": "llm_api_key", "label": "LLM API Key", "value": _mask(settings.llm_api_key), "masked": True},
        {"key": "deepseek_api_key", "label": "DeepSeek API Key", "value": _mask(settings.deepseek_api_key), "masked": True},
        {"key": "minio_secret_key", "label": "MinIO Secret Key", "value": _mask(settings.minio_secret_key), "masked": True},
    ]
    return {"editable": editable, "infra": infra}


def get_system_info(settings: Settings) -> dict:
    return {
        "app_name": settings.app_name,
        "version": APP_VERSION,
        "host": settings.host,
        "port": settings.port,
        "debug": settings.debug,
        "uptime_seconds": round(time.time() - START_TIME),
        "reload_mode": is_reload_mode(),
        "database": "sqlite" if "sqlite" in settings.resolved_database_url else "mysql",
        "llm_provider": settings.llm_provider,
        "embedding": f"{settings.embed_base_url} / {settings.embed_model}",
        "milvus": f"{settings.milvus_host}:{settings.milvus_port}",
        "storage": settings.storage_backend,
        "log_dir": str(settings.log_dir),
        "log_level": settings.log_level,
        "log_retention_days": settings.log_retention_days,
        "default_kb": f"{settings.default_kb_name}（{settings.default_kb_id}）",
    }


# ---------------- .env 写回 ----------------

def _write_env_key(text: str, env_key: str, value: str) -> str:
    """按 key 替换 .env 中的行；不存在则追加。保留注释与无关行。"""
    pattern = re.compile(rf"^{re.escape(env_key)}=.*$", re.MULTILINE)
    line = f"{env_key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text)
    return text.rstrip("\n") + "\n" + line + "\n"


def _atomic_write(text: str) -> None:
    """临时文件 + os.replace 原子写，防止写坏 .env。"""
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), prefix=".env.", suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, ENV_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fmt_value(value, coerce: str) -> str:
    if coerce == "int":
        return str(int(value))
    # float：去掉尾零与多余小数点
    return f"{value:g}"


def _validate(key: str, meta: dict, raw) -> str:
    """校验单个参数，返回规范化后的字符串值；非法抛 ValueError。"""
    if meta["coerce"] == "enum":
        if raw not in meta["options"]:
            raise ValueError(f"{meta['label']} 取值需为 {meta['options']}")
        return str(raw)
    try:
        if meta["coerce"] == "int":
            value = int(raw)
        else:
            value = float(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{meta['label']} 必须是数字") from e
    if not (meta["min"] <= value <= meta["max"]):
        raise ValueError(f"{meta['label']} 需在 {meta['min']} ~ {meta['max']} 之间")
    return _fmt_value(value, meta["coerce"])


def save_params(payload: dict) -> dict:
    """校验并保存可编辑参数到 .env，触发热重载。返回 {saved, needs_restart}。"""
    unknown = [k for k in payload if k not in EDITABLE_PARAMS]
    if unknown:
        raise ValueError(f"不可编辑参数：{', '.join(unknown)}")

    lines = []
    for key, meta in EDITABLE_PARAMS.items():
        if key not in payload:
            continue
        env_key = key.upper()
        value_str = _validate(key, meta, payload[key])
        lines.append((env_key, value_str))

    text = _read_env_text()
    for env_key, value_str in lines:
        text = _write_env_key(text, env_key, value_str)
    _atomic_write(text)

    # 延迟 spawn 新进程并退出自身 → 自动重启生效；spawn 失败则提示手动重启
    restart_ok = _schedule_restart()
    return {"saved": [k for k in payload], "needs_restart": not restart_ok}


def _read_env_text() -> str:
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8")
    return ""


def _schedule_restart() -> bool:
    """延迟 spawn 新后端进程（KB_WAIT_PORT=1 等待端口释放）后退出自身。

    延迟 1.5s 保证保存接口响应先完整返回，避免请求被重启打断。
    返回 spawn 是否成功；成功时调用方应预期进程即将退出。
    """
    import logging

    logger = logging.getLogger("app.config")
    try:
        # 关键：剔除可编辑参数对应的环境变量后再 spawn。
        # pymilvus 在 import 时执行 load_dotenv()，会把 CWD/.env 的旧值注入 os.environ；
        # 若原样继承，新进程里 pydantic-settings（环境变量优先级高于 .env 文件）会读到
        # 保存前的旧值，导致刚写入 .env 的新参数不生效。
        env = {**os.environ, "KB_WAIT_PORT": "1"}
        for key in EDITABLE_PARAMS:
            env.pop(key.upper(), None)
        # Windows 下优先用 pythonw.exe（无控制台版本）。
        # venv 的 python.exe 是 launcher stub，会二次 spawn 真正的 python.exe；
        # 二次 spawn 不继承父进程的 CREATE_NO_WINDOW，导致仍弹出黑色控制台窗口。
        # pythonw.exe 的 launcher 同样二次 spawn，但目标是无控制台的 pythonw，
        # 从根本上不创建控制台窗口。
        python_exe = sys.executable
        if sys.platform == "win32":
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if pythonw.exists():
                python_exe = str(pythonw)
        # CREATE_NO_WINDOW + STARTUPINFO(SW_HIDE) 双保险，抑制任何控制台窗口。
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        proc = subprocess.Popen(
            [python_exe, "-m", "app.run"],
            cwd=str(BASE_DIR),
            env=env,
            creationflags=creationflags,
            startupinfo=startupinfo,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.warning("config: spawned restart pid=%s (self pid=%s)", proc.pid, os.getpid())
    except Exception as e:  # noqa: BLE001 重启失败不阻断保存结果
        logger.error("config: spawn restart failed: %s", e)
        return False

    def _exit():
        import time as _t

        _t.sleep(1.5)
        logger.warning("config: self pid=%s calling os._exit", os.getpid())
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return True
