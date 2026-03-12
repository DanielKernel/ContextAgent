"""Unit tests for OpenJiuwenRetrieverAdapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from context_agent.adapters.retriever_adapter import OpenJiuwenRetrieverAdapter
from context_agent.utils.errors import AdapterError, ErrorCode


@pytest.mark.asyncio
class TestOpenJiuwenRetrieverAdapter:
    async def test_agentic_search_logs_and_raises_adapter_error(self):
        hybrid = AsyncMock()
        agentic = AsyncMock()
        agentic.retrieve = AsyncMock(side_effect=RuntimeError("agentic boom"))
        adapter = OpenJiuwenRetrieverAdapter(hybrid, agentic)

        with patch("context_agent.adapters.retriever_adapter.logger.warning") as warning:
            with pytest.raises(AdapterError) as exc_info:
                await adapter.agentic_search("scope-1", "query", "locator")

        assert exc_info.value.code == ErrorCode.RETRIEVAL_FAILED
        warning.assert_called_once()

    async def test_graph_search_logs_and_raises_adapter_error(self):
        hybrid = AsyncMock()
        agentic = AsyncMock()
        graph = AsyncMock()
        graph.retrieve = AsyncMock(side_effect=RuntimeError("graph boom"))
        adapter = OpenJiuwenRetrieverAdapter(hybrid, agentic, graph_retriever=graph)

        with patch("context_agent.adapters.retriever_adapter.logger.warning") as warning:
            with pytest.raises(AdapterError) as exc_info:
                await adapter.graph_search("scope-1", "entity")

        assert exc_info.value.code == ErrorCode.GRAPH_DB_UNAVAILABLE
        warning.assert_called_once()

    async def test_health_check_logs_debug_on_failure(self):
        hybrid = AsyncMock()
        hybrid.retrieve = AsyncMock(side_effect=RuntimeError("health boom"))
        adapter = OpenJiuwenRetrieverAdapter(hybrid, AsyncMock())

        with patch("context_agent.adapters.retriever_adapter.logger.debug") as debug:
            ok = await adapter.health_check()

        assert ok is False
        debug.assert_called_once()

    async def test_hybrid_search_maps_results(self):
        hybrid = AsyncMock()
        hybrid.retrieve = AsyncMock(return_value=[SimpleNamespace(content="doc", score=0.8, id="1")])
        adapter = OpenJiuwenRetrieverAdapter(hybrid, AsyncMock())

        items = await adapter.hybrid_search("scope-1", "query")

        assert len(items) == 1
        assert items[0].content == "doc"
        assert items[0].score == pytest.approx(0.8)
