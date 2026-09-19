"""大语言模型端口。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str: ...

    def chat_stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]: ...
