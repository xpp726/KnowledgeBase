"""OpenAI-compatible LLM 基础设施实现。"""

from .openai_compatible import LLMProvider, get_llm

__all__ = ["LLMProvider", "get_llm"]
