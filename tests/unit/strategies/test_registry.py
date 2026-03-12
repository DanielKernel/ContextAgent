"""Unit tests for StrategyRegistry and compression strategies."""

from __future__ import annotations

import pytest

from context_agent.models.context import ContextItem, ContextOutput, ContextSnapshot, OutputType
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.registry import (
    StrategyRegistry,
    ensure_default_strategies_registered,
)
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
