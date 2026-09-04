"""LLM 抽象层：统一 OpenAI 兼容接口的封装，支持多 provider 热切换。

设计目标：
- 业务代码只依赖 `get_llm()` 返回的 LLMProvider，不关心底层是哪个模型。
- provider 差异全部收敛到配置（base_url / api_key / model / extra_body），代码零改动。
- 开发期用 DeepSeek 公网调通，上线切回内网 vLLM，改一个环境变量即可。

支持的 provider（通过 LLM_PROVIDER 切换）：
- qwen           内网 vLLM 上的 Qwen3-27B-FP8（需关闭思考模式）
- deepseek       DeepSeek 公网官方 API（deepseek-chat / deepseek-reasoner）
- deepseek_intra 内网自部署的 DeepSeek（OpenAI 兼容接口，地址自填）
- openai         任意 OpenAI 兼容端点（兜底）

实测约束（2026-09-03）：
- Qwen3 思考模式默认开启，必须传 chat_template_kwargs {"enable_thinking": false}，
  否则每题白白多耗 1-2 秒。DeepSeek 无此参数，不能传。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from app.config import get_settings


@dataclass
class LLMProvider:
    """一个 OpenAI 兼容 LLM 端点的完整描述。"""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 300.0
    max_tokens: int = 1024
    temperature: float = 0.3
    # 附加到请求体的额外字段（如 Qwen3 的 chat_template_kwargs）
    extra_body: dict = field(default_factory=dict)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if self.extra_body:
            payload.update(self.extra_body)
        return payload

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """非流式对话，返回完整回答文本。"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self.chat_url,
                headers=self._headers(),
                json=self._build_payload(
                    messages, stream=False, max_tokens=max_tokens, temperature=temperature
                ),
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"].get("content", "") or ""

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """SSE 流式对话，逐段 yield 增量文本（delta.content）。

        兼容 OpenAI 流式协议；Qwen3 思考模式下首帧可能是 reasoning_content，
        这里只产出 content，思考内容被静默跳过。
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.chat_url,
                headers=self._headers(),
                json=self._build_payload(
                    messages, stream=True, max_tokens=max_tokens, temperature=temperature
                ),
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        import json as _json

                        chunk = _json.loads(data)
                    except Exception:  # noqa: BLE001
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content


def _build_qwen(settings) -> LLMProvider:
    """内网 vLLM Qwen3-27B-FP8。必须关闭思考模式。"""
    return LLMProvider(
        name="qwen",
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": settings.llm_enable_thinking}},
    )


def _build_deepseek(settings) -> LLMProvider:
    """DeepSeek 公网官方 API。无 chat_template_kwargs。"""
    return LLMProvider(
        name="deepseek",
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )


def _build_deepseek_intra(settings) -> LLMProvider:
    """内网自部署 DeepSeek（OpenAI 兼容接口）。"""
    return LLMProvider(
        name="deepseek_intra",
        base_url=settings.deepseek_intra_base_url,
        api_key=settings.deepseek_intra_api_key,
        model=settings.deepseek_intra_model,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )


_BUILDERS = {
    "qwen": _build_qwen,
    "deepseek": _build_deepseek,
    "deepseek_intra": _build_deepseek_intra,
}


def get_llm() -> LLMProvider:
    """根据 LLM_PROVIDER 返回对应端点（缓存于进程内）。"""
    settings = get_settings()
    builder = _BUILDERS.get(settings.llm_provider, _build_qwen)
    return builder(settings)
