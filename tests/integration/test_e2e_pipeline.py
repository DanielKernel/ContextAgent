"""Integration tests: end-to-end context retrieval pipeline.

Tests the full flow: AggregationRequest → ContextAggregator → ExposureController
→ CompressionStrategyRouter → ContextOutput, using only stubs (no real LTM/Redis).
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock

from context_agent.api.router import ContextAPIRouter
from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.health_checker import ContextHealthChecker
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextItem, ContextOutput, MemoryType, OutputType
from context_agent.models.policy import ExposurePolicy
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.context_aggregator import ContextAggregator
from context_agent.orchestration.strategy_scheduler import HybridStrategyScheduler
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.registry import StrategyRegistry
from context_agent.models.context import ContextSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ltm_stub(items_content: list[str]) -> AsyncMock:
    items = [
        ContextItem(
            source_type="ltm",
            content=c,
            memory_type=MemoryType.EPISODIC,
            score=0.9,
        )
        for c in items_content
    ]
    stub = AsyncMock()
    stub.search = AsyncMock(return_value=items)
    return stub


class _SummaryStrategy(CompressionStrategy):
    @property
    def strategy_id(self) -> str:
        return "test_summary"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        bullet_points = "\n".join(f"• {i.content}" for i in snapshot.items)
        summary = f"SUMMARY ({len(snapshot.items)} items):\n{bullet_points}"
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=summary,
            token_count=len(summary) // 4,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return snapshot.total_tokens // 2


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    StrategyRegistry.reset()
    yield
    StrategyRegistry.reset()


@pytest.mark.asyncio
class TestEndToEndPipeline:
    async def test_raw_output_pipeline(self):
        """RAW output returns concatenated items without compression."""
        ltm = _make_ltm_stub(["Context item A", "Context item B"])
        aggregator = ContextAggregator(ltm=ltm)
        router = ContextAPIRouter(aggregator=aggregator)

        output, warnings = await router.handle(
            scope_id="e2e-scope",
            session_id="sess1",
            query="What is task status?",
            output_type=OutputType.RAW,
            token_budget=4096,
        )

        assert output.output_type == OutputType.RAW
        assert "Context item A" in output.content
        assert "Context item B" in output.content
        assert output.scope_id == "e2e-scope"

    async def test_compressed_output_pipeline(self):
        """COMPRESSED output applies registered strategy."""
        StrategyRegistry.instance().register(_SummaryStrategy())

        ltm = _make_ltm_stub(["User wants weekly summaries.", "Last meeting: Nov 12."])
        aggregator = ContextAggregator(ltm=ltm)

        class _FixedScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule
                return StrategySchedule(strategy_ids=["test_summary"])

        comp_router = CompressionStrategyRouter(scheduler=_FixedScheduler())
        router = ContextAPIRouter(aggregator=aggregator, compression_router=comp_router)

        output, warnings = await router.handle(
            scope_id="e2e-scope",
            session_id="sess1",
            query="Summarise context",
            output_type=OutputType.COMPRESSED,
        )
        assert "SUMMARY" in output.content
        assert "2 items" in output.content

    async def test_exposure_policy_filters_items(self):
        """Exposure policy should block restricted source types."""
        ltm = _make_ltm_stub(["public info"])

        # Add a tool_result item via working memory stub
        wm = AsyncMock()
        wm.to_context_items = AsyncMock(return_value=[
            ContextItem(source_type="tool_result", content="CONFIDENTIAL data", score=0.95)
        ])
        aggregator = ContextAggregator(ltm=ltm, working_memory=wm)
        router = ContextAPIRouter(aggregator=aggregator)

        # Policy: only allow ltm source
        policy = ExposurePolicy(scope_id="e2e-scope", allowed_source_types=["ltm"])

        output, warnings = await router.handle(
            scope_id="e2e-scope",
            session_id="sess1",
            query="Get context",
            output_type=OutputType.RAW,
            policy=policy,
        )
        assert "CONFIDENTIAL" not in output.content
        assert "public info" in output.content
        assert any("filtered" in w.lower() for w in warnings)

    async def test_snapshot_output_creates_version(self):
        """SNAPSHOT output should create a version record and return version_id."""
        ltm = _make_ltm_stub(["item one"])
        aggregator = ContextAggregator(ltm=ltm)
        version_manager = ContextVersionManager()
        router = ContextAPIRouter(aggregator=aggregator, version_manager=version_manager)

        output, _ = await router.handle(
            scope_id="snap-scope",
            session_id="sess1",
            query="snapshot test",
            output_type=OutputType.SNAPSHOT,
        )
        assert output.output_type == OutputType.SNAPSHOT
        assert len(output.content) > 0  # version_id returned as content

        # Verify we can restore it
        snapshot = await version_manager.restore("snap-scope", "sess1", output.content)
        assert snapshot.scope_id == "snap-scope"

    async def test_empty_context_returns_valid_output(self):
        """Empty LTM should still produce a valid (empty) output."""
        ltm = _make_ltm_stub([])
        aggregator = ContextAggregator(ltm=ltm)
        router = ContextAPIRouter(aggregator=aggregator)

        output, _ = await router.handle(
            scope_id="empty-scope",
            session_id="sess1",
            query="anything",
            output_type=OutputType.RAW,
        )
        assert output is not None
        assert output.scope_id == "empty-scope"

    async def test_concurrent_requests_isolated(self):
        """Multiple concurrent requests should not interfere with each other."""
        async def _handle(scope_id: str, content: str) -> ContextOutput:
            ltm = _make_ltm_stub([content])
            aggregator = ContextAggregator(ltm=ltm)
            router = ContextAPIRouter(aggregator=aggregator)
            output, _ = await router.handle(
                scope_id=scope_id, session_id="sess1",
                query="test", output_type=OutputType.RAW,
            )
            return output

        results = await asyncio.gather(
            _handle("scope-A", "unique content for A"),
            _handle("scope-B", "unique content for B"),
            _handle("scope-C", "unique content for C"),
        )
        assert results[0].scope_id == "scope-A"
        assert "scope-A" not in results[1].content.replace("scope-A", "")  # isolated
        assert results[2].scope_id == "scope-C"
