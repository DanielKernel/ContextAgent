"""Unit tests for UnifiedSearchCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_agent.core.retrieval.search_coordinator import (
    RetrievalPlan,
    UnifiedSearchCoordinator,
)
from context_agent.models.context import ContextItem, MemoryType


def _items(n: int, id_prefix: str = "i") -> list[ContextItem]:
    return [
        ContextItem(source_type="test", content=f"content {id_prefix}{i}", score=1.0 - i * 0.1)
        for i in range(n)
    ]


def _mock_retriever(hybrid=None, graph=None, rerank=None):
    r = AsyncMock()
    r.hybrid_search = AsyncMock(return_value=hybrid or [])
    r.graph_search = AsyncMock(return_value=graph or [])
    r.rerank = AsyncMock(side_effect=lambda q, items, k: items[:k])
    return r


@pytest.mark.asyncio
class TestUnifiedSearchCoordinator:
    async def test_hybrid_search_called(self):
        items = _items(5, "h")
        retriever = _mock_retriever(hybrid=items)
        plan = RetrievalPlan(query="test query", scope_id="s1", enable_hybrid=True)
        coordinator = UnifiedSearchCoordinator(retriever=retriever)
        results = await coordinator.search(plan)
        retriever.hybrid_search.assert_awaited_once()
        assert len(results) <= plan.top_k

    async def test_graph_search_combined(self):
        h_items = _items(3, "h")
        g_items = _items(3, "g")
        retriever = _mock_retriever(hybrid=h_items, graph=g_items)
        plan = RetrievalPlan(
            query="q", scope_id="s1", enable_graph=True, rerank=False
        )
        coordinator = UnifiedSearchCoordinator(retriever=retriever)
        results = await coordinator.search(plan)
        # Results should include items from both paths (up to top_k)
        assert len(results) > 0

    async def test_rrf_fusion_deduplication(self):
        shared_item = ContextItem(source_type="ltm", content="shared", score=0.9)
        # Same item in both lists
        list1 = [shared_item.model_copy()]
        list2 = [shared_item.model_copy()]
        fused = UnifiedSearchCoordinator._rrf_fuse([list1, list2], top_k=5)
        ids = [i.item_id for i in fused]
        assert ids.count(shared_item.item_id) == 1

    async def test_ltm_combined(self):
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=_items(5, "m"))
        retriever = _mock_retriever()
        plan = RetrievalPlan(
            query="q", scope_id="s1", enable_hybrid=False, enable_ltm=True, rerank=False
        )
        coordinator = UnifiedSearchCoordinator(retriever=retriever, ltm=ltm)
        results = await coordinator.search(plan)
        ltm.search.assert_awaited_once()
        assert len(results) == 5

    async def test_failed_path_skipped(self):
        retriever = _mock_retriever()
        retriever.hybrid_search = AsyncMock(side_effect=RuntimeError("retriever down"))
        plan = RetrievalPlan(query="q", scope_id="s1", enable_hybrid=True, rerank=False)
        coordinator = UnifiedSearchCoordinator(retriever=retriever)
        # Should not raise
        results = await coordinator.search(plan)
        assert results == []

    async def test_task_conditioning_promotes_execution_memories(self):
        semantic = ContextItem(
            source_type="ltm",
            content="background company history",
            score=0.55,
            memory_type=MemoryType.SEMANTIC,
        )
        procedural = ContextItem(
            source_type="ltm",
            content="deployment runbook",
            score=0.49,
            memory_type=MemoryType.PROCEDURAL,
            tier="hot",
        )
        retriever = _mock_retriever(hybrid=[semantic, procedural])
        plan = RetrievalPlan(
            query="deploy the service",
            scope_id="s1",
            task_type="task",
            agent_role="executor",
            rerank=False,
        )
        coordinator = UnifiedSearchCoordinator(retriever=retriever)

        results = await coordinator.search(plan)

        assert results[0].memory_type == MemoryType.PROCEDURAL
