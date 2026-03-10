"""LLM adapter.

Defines LLMPort (ABC) for LLM-based operations (compression, summarization,
conflict detection) and an HTTP implementation using httpx.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class LLMPort(ABC):
    """Abstract interface for LLM text generation (compression / summarization)."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt and return the generated text response."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the LLM service is reachable."""


class HttpLLMAdapter(LLMPort):
    """HTTP-based LLM adapter (compatible with OpenAI-compatible APIs).

    Works with Ollama, vLLM, OpenAI, and any OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        api_key: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_s
        self._max_retries = max_retries
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
        )

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "LLM HTTP error",
                    status=exc.response.status_code,
                    attempt=attempt,
                )
                last_exc = exc
                if exc.response.status_code < 500:
                    break  # 4xx: don't retry
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("LLM connection error", attempt=attempt, error=str(exc))
                last_exc = exc
        raise AdapterError("LLM", str(last_exc), code=ErrorCode.LLM_SERVICE_ERROR) from last_exc

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            try:
                # Fallback: try a minimal completion
                await self.complete("ping", "ping", max_tokens=1)
                return True
            except Exception:
                return False

    async def close(self) -> None:
        await self._client.aclose()
