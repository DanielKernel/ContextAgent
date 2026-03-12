"""Performance smoke tests for key requirements use cases."""

from __future__ import annotations

import time
from statistics import quantiles
from unittest.mock import AsyncMock

import pytest

from context_agent.core.context.jit_resolver import JITResolver
from context_agent.core.memory.tiered_router import TieredMemoryRouter
from context_agent.core.retrieval.search_coordinator import RetrievalPlan, UnifiedSearchCoordinator
from context_agent.models.context import ContextItem, ContextSnapshot, MemoryType
from context_agent.models.note import NoteType, WorkingNote
from context_agent.orchestration.context_aggregator import AggregationRequest, ContextAggregator
from context_agent.strategies.realtime_strategy import RealtimeCompressionStrategy


def _p95(samples: list[float]) -> float:
    if len(samples) < 2:
        return samples[0]
    return quantiles(samples, n=100, method="inclusive")[94]


def _item(content: str, memory_type: MemoryType = MemoryType.SEMANTIC) -> ContextItem:
    return ContextItem(source_type="ltm", content=content, memory_type=memory_type, score=0.9)


@pytest.mark.asyncio
class TestUseCaseLatencySmoke:
    async def test_uc001_aggregation_internal_sources_p95_under_200ms(self):
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[_item("customer preference")])
        aggregator = ContextAggregator(ltm=ltm)

        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            await aggregator.aggregate(
                AggregationRequest(scope_id="scope-1", session_id="sess-1", query="pref")
            )
            samples.append((time.perf_counter() - t0) * 1000)

        assert _p95(samples) < 200.0

    async def test_uc002_hot_tier_recall_p95_under_20ms(self):
        ltm = AsyncMock()
        router = TieredMemoryRouter(ltm=ltm)
        await router.warm_cache("scope-1", [_item("recent variable", MemoryType.VARIABLE)])

        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            await router.search(
                "scope-1",
                "recent",
                top_k=1,
                memory_types=[MemoryType.VARIABLE],
            )
            samples.append((time.perf_counter() - t0) * 1000)

        assert _p95(samples) < 20.0

    async def test_uc004_scratchpad_jit_p95_under_30ms(self):
        retriever = AsyncMock()
        working_memory = AsyncMock()
        note = WorkingNote(
            scope_id="scope-1",
            session_id="sess-1",
            note_type=NoteType.CURRENT_STATUS,
            content={"status": "active"},
        )
        working_memory.get_note = AsyncMock(return_value=note)
        resolver = JITResolver(retriever=retriever, working_memory=working_memory)

        from context_agent.models.ref import ContextRef, RefType

        ref = ContextRef(ref_type=RefType.SCRATCHPAD, scope_id="scope-1", locator="sess-1:any")

        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            await resolver.resolve(ref)
            samples.append((time.perf_counter() - t0) * 1000)

        assert _p95(samples) < 30.0

    async def test_uc009_realtime_compression_p95_under_50ms(self):
        strategy = RealtimeCompressionStrategy()
        snapshot = ContextSnapshot(
            scope_id="scope-1",
            session_id="sess-1",
            token_budget=64,
            items=[
                ContextItem(source_type="user", content="x" * 120, metadata={"role": "user"})
                for _ in range(12)
            ],
        )
        snapshot.total_tokens = sum(len(item.content) // 4 for item in snapshot.items)

        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            await strategy.compress(snapshot)
            samples.append((time.perf_counter() - t0) * 1000)

        assert _p95(samples) < 50.0

    async def test_uc012_hybrid_search_p95_under_300ms(self):
        retriever = AsyncMock()
        retriever.hybrid_search = AsyncMock(return_value=[_item("hybrid result")])
        retriever.graph_search = AsyncMock(return_value=[_item("graph result")])
        retriever.rerank = AsyncMock(side_effect=lambda query, items, top_k: items[:top_k])
        coordinator = UnifiedSearchCoordinator(retriever=retriever)
        plan = RetrievalPlan(query="q", scope_id="scope-1", enable_hybrid=True, enable_graph=True)

        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            await coordinator.search(plan)
            samples.append((time.perf_counter() - t0) * 1000)

        assert _p95(samples) < 300.0
