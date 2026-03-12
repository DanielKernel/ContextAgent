"""Unit tests for OpenJiuwenContextEngineAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_agent.adapters.context_engine_adapter import OpenJiuwenContextEngineAdapter
from context_agent.utils.errors import AdapterError, ErrorCode


@pytest.mark.asyncio
class TestOpenJiuwenContextEngineAdapter:
    async def test_get_context_accepts_message_list(self):
        context_engine = AsyncMock()
        context_engine.get_context = AsyncMock(return_value=[{"role": "user", "content": "hi"}])
        adapter = OpenJiuwenContextEngineAdapter(context_engine)

        messages = await adapter.get_context("scope-1", "sess-1")

        assert messages == [{"role": "user", "content": "hi"}]

    async def test_get_context_accepts_dict_with_messages(self):
        context_engine = AsyncMock()
        context_engine.get_context = AsyncMock(
            return_value={"messages": [{"role": "assistant", "content": "hello"}]}
        )
        adapter = OpenJiuwenContextEngineAdapter(context_engine)

        messages = await adapter.get_context("scope-1", "sess-1")

        assert messages == [{"role": "assistant", "content": "hello"}]

    async def test_get_context_rejects_non_list_messages_payload(self):
        context_engine = AsyncMock()
        context_engine.get_context = AsyncMock(return_value={"messages": "not-a-list"})
        adapter = OpenJiuwenContextEngineAdapter(context_engine)

        with pytest.raises(AdapterError) as exc_info:
            await adapter.get_context("scope-1", "sess-1")

        assert exc_info.value.code == ErrorCode.ADAPTER_MAPPING_ERROR

    async def test_get_context_rejects_unsupported_payload_type(self):
        context_engine = AsyncMock()
        context_engine.get_context = AsyncMock(return_value="not-supported")
        adapter = OpenJiuwenContextEngineAdapter(context_engine)

        with pytest.raises(AdapterError) as exc_info:
            await adapter.get_context("scope-1", "sess-1")

        assert exc_info.value.code == ErrorCode.ADAPTER_MAPPING_ERROR

    async def test_health_check_logs_and_returns_false_on_failure(self):
        context_engine = AsyncMock()
        context_engine.get_context = AsyncMock(side_effect=RuntimeError("boom"))
        adapter = OpenJiuwenContextEngineAdapter(context_engine)

        with patch("context_agent.adapters.context_engine_adapter.logger.debug") as debug:
            ok = await adapter.health_check()

        assert ok is False
        debug.assert_called_once()
