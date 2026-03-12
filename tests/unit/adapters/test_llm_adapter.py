"""Unit tests for HttpLLMAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_agent.adapters.llm_adapter import HttpLLMAdapter
from context_agent.utils.errors import AdapterError, ErrorCode


@pytest.mark.asyncio
class TestHttpLLMAdapter:
    async def test_complete_returns_message_content(self):
        adapter = HttpLLMAdapter("https://example.com", "demo-model")
        original_client = adapter._client
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
        }
        adapter._client = AsyncMock()
        adapter._client.post = AsyncMock(return_value=response)

        result = await adapter.complete("system", "user")

        assert result == "hello"
        await original_client.aclose()
        await adapter.close()

    async def test_complete_rejects_malformed_payload(self):
        adapter = HttpLLMAdapter("https://example.com", "demo-model")
        original_client = adapter._client
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": []}
        adapter._client = AsyncMock()
        adapter._client.post = AsyncMock(return_value=response)

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete("system", "user")

        assert exc_info.value.code == ErrorCode.ADAPTER_MAPPING_ERROR
        await original_client.aclose()
        await adapter.close()

    async def test_health_check_logs_fallback_failures(self):
        adapter = HttpLLMAdapter("https://example.com", "demo-model")
        original_client = adapter._client
        adapter._client = AsyncMock()
        adapter._client.get = AsyncMock(side_effect=RuntimeError("health boom"))

        with patch.object(adapter, "complete", AsyncMock(side_effect=AdapterError("LLM", "fallback boom"))):
            with patch("context_agent.adapters.llm_adapter.logger.debug") as debug:
                ok = await adapter.health_check()

        assert ok is False
        assert debug.call_count == 2
        await original_client.aclose()
        await adapter.close()

    async def test_health_check_uses_completion_fallback(self):
        adapter = HttpLLMAdapter("https://example.com", "demo-model")
        original_client = adapter._client
        adapter._client = AsyncMock()
        adapter._client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        with patch.object(adapter, "complete", AsyncMock(return_value="pong")) as complete:
            ok = await adapter.health_check()

        assert ok is True
        complete.assert_awaited_once()
        await original_client.aclose()
        await adapter.close()
