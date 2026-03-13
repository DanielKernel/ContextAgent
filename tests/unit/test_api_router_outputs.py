"""Tests for ContextAPIRouter output-type routing (UC007)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_agent.api.router import ContextAPIRouter
from context_agent.models.context import (
    ContextItem,
    ContextOutput,
    ContextSnapshot,
    MemoryType,
    OutputType,
)


def _snapshot() -> ContextSnapshot:
    item = ContextItem(source_type="ltm", content="retrieved memory", score=0.9)
    return ContextSnapshot(
        scope_id="scope-1",
        session_id="sess-1",
        query="find context",
        items=[item],
        total_tokens=len(item.content) // 4,
        token_budget=256,
    )


@pytest.mark.asyncio
class TestContextAPIRouterOutputs:
    async def test_search_output_uses_tiered_router_results(self):
        aggregator = AsyncMock()
        aggregator.aggregate = AsyncMock(return_value=_snapshot())
        tiered_router = AsyncMock()
        tiered_item = ContextItem(source_type="ltm", content="tiered result", score=0.95)
        tiered_router.search = AsyncMock(return_value=([tiered_item], {"hot": 1.2}))
        router = ContextAPIRouter(
            aggregator=aggregator,
            tiered_router=tiered_router,
        )

        output, warnings = await router.handle(
            scope_id="scope-1",
            session_id="sess-1",
            query="lookup",
            output_type=OutputType.SEARCH,
            top_k=3,
        )

        assert warnings == []
        assert output.output_type == OutputType.SEARCH
        assert output.search_items is not None
        assert output.search_items[0].content == "tiered result"
        tiered_router.search.assert_awaited_once()

    async def test_summary_output_wraps_compressed_text(self):
        aggregator = AsyncMock()
        aggregator.aggregate = AsyncMock(return_value=_snapshot())
        compression_router = MagicMock()
        compression_router.route_and_compress = AsyncMock(
            return_value=ContextOutput(
                scope_id="scope-1",
                session_id="sess-1",
                output_type=OutputType.COMPRESSED,
                content="summary text",
                token_count=3,
            )
        )
        router = ContextAPIRouter(
            aggregator=aggregator,
            compression_router=compression_router,
        )

        output, _ = await router.handle(
            scope_id="scope-1",
            session_id="sess-1",
            query="summarize",
            output_type=OutputType.SUMMARY,
        )

        assert output.output_type == OutputType.SUMMARY
        assert output.compressed_text == "summary text"
        assert output.content == "summary text"

    async def test_compressed_background_output_preserves_content(self):
        aggregator = AsyncMock()
        aggregator.aggregate = AsyncMock(return_value=_snapshot())
        compression_router = MagicMock()
        compression_router.route_and_compress = AsyncMock(
            return_value=ContextOutput(
                scope_id="scope-1",
                session_id="sess-1",
                output_type=OutputType.COMPRESSED,
                content="background text",
                token_count=4,
            )
        )
        router = ContextAPIRouter(
            aggregator=aggregator,
            compression_router=compression_router,
        )

        output, _ = await router.handle(
            scope_id="scope-1",
            session_id="sess-1",
            query="background",
            output_type=OutputType.COMPRESSED_BACKGROUND,
        )

        assert output.output_type == OutputType.COMPRESSED_BACKGROUND
        assert output.compressed_text == "background text"
        assert output.content == "background text"

    async def test_warnings_include_degraded_sources_and_output(self):
        snapshot = _snapshot()
        snapshot.degraded_sources = ["ltm"]
        aggregator = AsyncMock()
        aggregator.aggregate = AsyncMock(return_value=snapshot)
        compression_router = MagicMock()
        compression_router.route_and_compress = AsyncMock(
            return_value=ContextOutput(
                scope_id="scope-1",
                session_id="sess-1",
                output_type=OutputType.COMPRESSED,
                content="fallback text",
                token_count=3,
                degraded=True,
                error="compression_fallback_raw",
            )
        )
        router = ContextAPIRouter(
            aggregator=aggregator,
            compression_router=compression_router,
        )

        output, warnings = await router.handle(
            scope_id="scope-1",
            session_id="sess-1",
            query="summarize",
            output_type=OutputType.COMPRESSED,
        )

        assert output.degraded is True
        assert any("Degraded sources: ltm" == warning for warning in warnings)
        assert any("Output degraded: compression_fallback_raw" == warning for warning in warnings)

    async def test_search_output_applies_task_conditioning_to_tiered_results(self):
        aggregator = AsyncMock()
        aggregator.aggregate = AsyncMock(return_value=_snapshot())
        tiered_router = AsyncMock()
        semantic = ContextItem(
            source_type="ltm",
            content="background policy",
            score=0.55,
            memory_type=MemoryType.SEMANTIC,
        )
        procedural = ContextItem(
            source_type="ltm",
            content="deployment checklist",
            score=0.49,
            memory_type=MemoryType.PROCEDURAL,
            tier="hot",
        )
        tiered_router.search = AsyncMock(return_value=([semantic, procedural], {"hot": 1.2}))
        router = ContextAPIRouter(
            aggregator=aggregator,
            tiered_router=tiered_router,
        )

        output, warnings = await router.handle(
            scope_id="scope-1",
            session_id="sess-1",
            query="deploy",
            output_type=OutputType.SEARCH,
            task_type="task",
            agent_role="executor",
            top_k=2,
        )

        assert warnings == []
        assert output.search_items is not None
        assert output.search_items[0].memory_type == MemoryType.PROCEDURAL
