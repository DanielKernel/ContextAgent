"""Unit tests for ContextAggregator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from context_agent.models.context import ContextItem, ContextSnapshot
from context_agent.orchestration.context_aggregator import (
    AggregationRequest,
    ContextAggregator,
)


def _make_items(n: int, content_prefix: str = "item") -> list[ContextItem]:
    return [
        ContextItem(source_type="ltm", content=f"{content_prefix}-{i}", score=1.0 - i * 0.1)
        for i in range(n)
    ]


@pytest.mark.asyncio
class TestContextAggregator:
    async def test_aggregates_from_ltm(self):
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=_make_items(3))

        aggregator = ContextAggregator(ltm=ltm)
        req = AggregationRequest(
            scope_id="s1",
            session_id="sess1",
            query="test query",
            token_budget=4096,
        )
        snapshot = await aggregator.aggregate(req)

        assert isinstance(snapshot, ContextSnapshot)
        assert len(snapshot.items) == 3
        ltm.search.assert_awaited_once_with("s1", "test query", 10)

    async def test_deduplication(self):
        # Return same item twice from different sources
        item = ContextItem(source_type="ltm", content="dup content", score=0.9)
        item2 = item.model_copy(update={"score": 0.5})  # same item_id, lower score

        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[item])

        wm = AsyncMock()
        wm.to_context_items = AsyncMock(return_value=[item2])

        aggregator = ContextAggregator(ltm=ltm, working_memory=wm)
        req = AggregationRequest(scope_id="s1", session_id="sess1", query="q")
        snapshot = await aggregator.aggregate(req)

        # Deduplication keeps the highest-scored version
        matching = [i for i in snapshot.items if i.item_id == item.item_id]
        assert len(matching) == 1
        assert matching[0].score == 0.9

    async def test_token_budget_enforced(self):
        # 10 items × 40 chars each ≈ 100 tokens; budget = 20 tokens
        items = [
            ContextItem(source_type="ltm", content="a" * 40, score=1.0)
            for _ in range(10)
        ]
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=items)

        aggregator = ContextAggregator(ltm=ltm)
        req = AggregationRequest(
            scope_id="s1", session_id="sess1", query="q", token_budget=20
        )
        snapshot = await aggregator.aggregate(req)
        assert snapshot.total_tokens <= 20

    async def test_source_failure_tolerated(self):
        ltm = AsyncMock()
        ltm.search = AsyncMock(side_effect=RuntimeError("LTM unavailable"))

        aggregator = ContextAggregator(ltm=ltm)
        req = AggregationRequest(scope_id="s1", session_id="sess1", query="q")
        # Should not raise
        snapshot = await aggregator.aggregate(req)
        assert snapshot.items == []
        assert snapshot.degraded_sources == ["ltm"]

    async def test_timeout_marks_sources_as_degraded(self):
        async def _slow_items(*args, **kwargs):
            await asyncio.sleep(0.05)
            return _make_items(1)

        ltm = AsyncMock()
        ltm.search = AsyncMock(side_effect=_slow_items)
        wm = AsyncMock()
        wm.to_context_items = AsyncMock(side_effect=_slow_items)

        aggregator = ContextAggregator(ltm=ltm, working_memory=wm)
        req = AggregationRequest(
            scope_id="s1",
            session_id="sess1",
            query="q",
            timeout_ms=1.0,
        )

        snapshot = await aggregator.aggregate(req)

        assert snapshot.items == []
        assert set(snapshot.degraded_sources) == {"ltm", "working_memory"}

    async def test_no_sources_returns_empty_snapshot(self):
        aggregator = ContextAggregator()
        req = AggregationRequest(scope_id="s1", session_id="sess1", query="q")
        snapshot = await aggregator.aggregate(req)
        assert isinstance(snapshot, ContextSnapshot)
        assert snapshot.scope_id == "s1"
