"""Unit tests for StrategyRegistry and compression strategies."""

from __future__ import annotations

import pytest

from context_agent.models.context import ContextItem, ContextOutput, ContextSnapshot, OutputType
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.compaction_strategy import CompactionStrategy
from context_agent.strategies.long_session_strategy import LongSessionCompressionStrategy
from context_agent.strategies.qa_strategy import QACompressionStrategy
from context_agent.strategies.task_strategy import TaskCompressionStrategy
from context_agent.strategies.registry import (
    StrategyRegistry,
    ensure_default_strategies_registered,
)
from context_agent.utils.errors import CompressionError
from context_agent.utils.errors import StrategyNotFoundError


class _DoubleStrategy(CompressionStrategy):
    """Test stub: returns content doubled."""

    @property
    def strategy_id(self) -> str:
        return "double_test"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        text = " | ".join(i.content for i in snapshot.items)
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=text,
            token_count=len(text) // 4,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return snapshot.total_tokens


def _make_snapshot(items_text: list[str] = None) -> ContextSnapshot:
    snap = ContextSnapshot(scope_id="test-scope", session_id="sess1")
    for t in (items_text or ["hello world"]):
        snap.add_item(ContextItem(source_type="ltm", content=t))
    snap.total_tokens = sum(len(t) // 4 for t in (items_text or ["hello world"]))
    return snap


class TestStrategyRegistry:
    def setup_method(self):
        StrategyRegistry.reset()

    def teardown_method(self):
        StrategyRegistry.reset()

    def test_register_and_get(self):
        registry = StrategyRegistry.instance()
        strat = _DoubleStrategy()
        registry.register(strat)
        assert registry.get("double_test") is strat

    def test_duplicate_raises(self):
        registry = StrategyRegistry.instance()
        registry.register(_DoubleStrategy())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_DoubleStrategy())

    def test_not_found_raises(self):
        registry = StrategyRegistry.instance()
        with pytest.raises(StrategyNotFoundError):
            registry.get("nonexistent")

    def test_list_strategies(self):
        registry = StrategyRegistry.instance()
        registry.register(_DoubleStrategy())
        assert "double_test" in registry.list()

    def test_unregister(self):
        registry = StrategyRegistry.instance()
        registry.register(_DoubleStrategy())
        registry.unregister("double_test")
        assert "double_test" not in registry.list()

    def test_ensure_default_strategies_registered(self):
        registry = StrategyRegistry.instance()
        ensure_default_strategies_registered()
        assert "qa" in registry.list()
        assert "task" in registry.list()

    def test_ensure_default_strategies_registered_refreshes_existing_llm_support(self):
        registry = StrategyRegistry.instance()
        ensure_default_strategies_registered()
        qa = registry.get("qa")
        task = registry.get("task")
        long_session = registry.get("long_session")
        compaction = registry.get("compaction")
        llm = object()

        ensure_default_strategies_registered(llm_adapter=llm)

        assert registry.get("qa") is qa
        assert registry.get("task") is task
        assert registry.get("long_session") is long_session
        assert registry.get("compaction") is compaction
        assert qa._llm is llm
        assert task._llm is llm
        assert long_session._llm is llm
        assert compaction._llm is llm


class TestDoubleStrategy:
    @pytest.mark.asyncio
    async def test_compress_basic(self):
        strat = _DoubleStrategy()
        snap = _make_snapshot(["foo", "bar"])
        out = await strat.compress(snap)
        assert "foo" in out.content
        assert "bar" in out.content
        assert out.output_type == OutputType.COMPRESSED

    def test_estimate_tokens(self):
        strat = _DoubleStrategy()
        snap = _make_snapshot(["hello world"])
        snap.total_tokens = 99
        assert strat.estimate_tokens(snap) == 99


class TestBuiltinStrategies:
    @pytest.mark.asyncio
    async def test_qa_strategy_returns_context_output(self):
        strat = QACompressionStrategy()
        snap = _make_snapshot(["alpha", "beta", "gamma"])
        snap.token_budget = 1

        out = await strat.compress(snap)

        assert isinstance(out, ContextOutput)
        assert out.output_type == OutputType.COMPRESSED
        assert out.scope_id == snap.scope_id

    @pytest.mark.asyncio
    async def test_qa_strategy_marks_truncation_fallback_as_degraded(self):
        class _BadLLM:
            async def complete(self, **kwargs):
                raise RuntimeError("boom")

        llm = _BadLLM()
        strat = QACompressionStrategy(llm_adapter=llm)
        snap = _make_snapshot(["alpha", "beta", "gamma"])
        snap.token_budget = 1

        out = await strat.compress(snap)

        assert out.degraded is True
        assert out.error == "qa_fallback_truncate"

    @pytest.mark.asyncio
    async def test_task_strategy_rejects_invalid_llm_payload(self):
        class _BadLLM:
            async def complete(self, **kwargs):
                return '{"not":"messages"}'

        strat = TaskCompressionStrategy(llm_adapter=_BadLLM())
        snap = _make_snapshot(["alpha", "beta", "gamma"])
        snap.token_budget = 1

        out = await strat.compress(snap)

        assert out.degraded is True
        assert out.error == "task_fallback_keep_recent"

    @pytest.mark.asyncio
    async def test_long_session_strategy_marks_simple_window_fallback(self):
        class _BadLLM:
            async def complete(self, **kwargs):
                raise RuntimeError("boom")

        strat = LongSessionCompressionStrategy(llm_adapter=_BadLLM())
        snap = _make_snapshot(["alpha", "beta", "gamma", "delta"])
        snap.token_budget = 1

        out = await strat.compress(snap)

        assert out.degraded is True
        assert out.error == "long_session_fallback_simple_window"

    @pytest.mark.asyncio
    async def test_compaction_strategy_rejects_invalid_compressed_messages(self):
        class _BadLLM:
            async def complete(self, **kwargs):
                return '{"compressed_messages":"bad"}'

        strat = CompactionStrategy(llm_adapter=_BadLLM())
        snap = _make_snapshot(["alpha", "beta", "gamma"])
        snap.token_budget = 1

        out = await strat.compress(snap)

        assert out.output_type == OutputType.STRUCTURED
        assert "[ltm]" in out.content or out.content == ""
