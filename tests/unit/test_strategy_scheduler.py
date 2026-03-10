"""Unit tests for HybridStrategyScheduler."""

from __future__ import annotations

import pytest

from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySelectionContext,
)
from context_agent.strategies.registry import StrategyRegistry
from context_agent.strategies.base import CompressionStrategy
from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType


class _StubStrategy(CompressionStrategy):
    def __init__(self, sid: str):
        self._id = sid

    @property
    def strategy_id(self) -> str:
        return self._id

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            content="stub",
            token_count=1,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return 1


class TestHybridStrategyScheduler:
    def setup_method(self):
        StrategyRegistry.reset()
        registry = StrategyRegistry.instance()
        for sid in ["qa_compression", "task_compression", "long_session_compression",
                    "realtime_compression", "compaction"]:
            registry.register(_StubStrategy(sid))

    def teardown_method(self):
        StrategyRegistry.reset()

    def test_qa_task_type(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(scope_id="s1", task_type="qa")
        schedule = scheduler.schedule(ctx)
        assert "qa_compression" in schedule.strategy_ids

    def test_task_type_selects_task_strategy(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(scope_id="s1", task_type="task")
        schedule = scheduler.schedule(ctx)
        assert "task_compression" in schedule.strategy_ids

    def test_high_utilisation_triggers_compaction(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(
            scope_id="s1", task_type="", token_used=3500, token_budget=4000
        )
        schedule = scheduler.schedule(ctx)
        assert "compaction" in schedule.strategy_ids

    def test_very_high_utilisation_prepends_realtime(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(
            scope_id="s1", task_type="qa", token_used=3999, token_budget=4000
        )
        schedule = scheduler.schedule(ctx)
        assert schedule.strategy_ids[0] == "realtime_compression"

    def test_long_session_detection(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(scope_id="s1", task_type="", turn_count=25)
        schedule = scheduler.schedule(ctx)
        assert "long_session_compression" in schedule.strategy_ids

    def test_graph_enabled_for_task_type(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(scope_id="s1", task_type="task")
        schedule = scheduler.schedule(ctx)
        assert schedule.enable_graph_retrieval is True

    def test_reviewer_ltm_disabled(self):
        scheduler = HybridStrategyScheduler()
        ctx = StrategySelectionContext(scope_id="s1", agent_role="reviewer")
        schedule = scheduler.schedule(ctx)
        assert schedule.enable_ltm is False
