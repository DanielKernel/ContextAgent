"""Functional tests for CompressionStrategyRouter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from context_agent.models.context import ContextItem, ContextOutput, ContextSnapshot, OutputType
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySelectionContext,
)
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.qa_strategy import QACompressionStrategy
from context_agent.strategies.registry import StrategyRegistry


class _EchoStrategy(CompressionStrategy):
    """Test strategy: returns the first item's content as output."""

    @property
    def strategy_id(self) -> str:
        return "echo"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        text = snapshot.items[0].content if snapshot.items else ""
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=f"[echo] {text}",
            token_count=len(text) // 4,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return snapshot.total_tokens


class _FailingStrategy(CompressionStrategy):
    @property
    def strategy_id(self) -> str:
        return "always_fail"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        raise RuntimeError("intentional failure")

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return 0


def _make_snapshot(content: str = "test content") -> ContextSnapshot:
    snap = ContextSnapshot(scope_id="s1", session_id="sess1")
    snap.add_item(ContextItem(source_type="ltm", content=content))
    snap.total_tokens = len(content) // 4
    return snap


def _ctx(task_type: str = "qa", utilisation: float = 0.5) -> StrategySelectionContext:
    budget = 4096
    return StrategySelectionContext(
        scope_id="s1",
        task_type=task_type,
        token_used=int(budget * utilisation),
        token_budget=budget,
    )


@pytest.mark.asyncio
class TestCompressionStrategyRouter:
    def setup_method(self):
        StrategyRegistry.reset()

    def teardown_method(self):
        StrategyRegistry.reset()

    async def test_routes_to_registered_strategy(self):
        StrategyRegistry.instance().register(_EchoStrategy())
        # Manually wire scheduler to return "echo"
        class _FixedScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule
                return StrategySchedule(strategy_ids=["echo"])

        router = CompressionStrategyRouter(scheduler=_FixedScheduler())
        snap = _make_snapshot("Hello world!")
        output = await router.route_and_compress(snap, _ctx())
        assert "[echo]" in output.content
        assert output.scope_id == "s1"

    async def test_fallback_to_raw_when_no_strategy(self):
        # No strategies registered → scheduler returns empty list → raw fallback
        router = CompressionStrategyRouter()
        snap = _make_snapshot("fallback content")
        output = await router.route_and_compress(snap, _ctx("unknown_type"))
        # Should return raw output without raising
        assert output.output_type == OutputType.RAW
        assert output.degraded is True
        assert output.error == "compression_fallback_raw"
        assert "fallback content" in output.content

    async def test_fallback_when_strategy_fails(self):
        StrategyRegistry.instance().register(_FailingStrategy())

        class _FixedScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule
                return StrategySchedule(strategy_ids=["always_fail"])

        router = CompressionStrategyRouter(scheduler=_FixedScheduler())
        snap = _make_snapshot("important content")
        # Should not raise; should fall back to raw
        output = await router.route_and_compress(snap, _ctx())
        assert output.output_type == OutputType.RAW
        assert output.degraded is True
        assert "intentional failure" in (output.error or "")

    async def test_tries_next_strategy_on_failure(self):
        """If first strategy fails, second should succeed."""
        StrategyRegistry.instance().register(_FailingStrategy())
        StrategyRegistry.instance().register(_EchoStrategy())

        class _TwoStrategyScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule
                return StrategySchedule(strategy_ids=["always_fail", "echo"])

        router = CompressionStrategyRouter(scheduler=_TwoStrategyScheduler())
        snap = _make_snapshot("second chance")
        output = await router.route_and_compress(snap, _ctx())
        assert "[echo]" in output.content

    async def test_output_has_correct_scope_and_session(self):
        StrategyRegistry.instance().register(_EchoStrategy())

        class _FixedScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule
                return StrategySchedule(strategy_ids=["echo"])

        router = CompressionStrategyRouter(scheduler=_FixedScheduler())
        snap = _make_snapshot("scope test")
        snap.session_id = "session-abc"
        output = await router.route_and_compress(snap, _ctx())
        assert output.scope_id == "s1"
        assert output.session_id == "session-abc"

    async def test_qa_strategy_receives_snapshot_token_budget(self):
        compressor = AsyncMock(
            return_value=[{"role": "assistant", "content": "compressed answer"}]
        )
        StrategyRegistry.instance().register(
            QACompressionStrategy(dialogue_compressor=type("C", (), {"compress": compressor})())
        )

        class _FixedScheduler(HybridStrategyScheduler):
            def schedule(self, ctx):
                from context_agent.orchestration.strategy_scheduler import StrategySchedule

                return StrategySchedule(strategy_ids=["qa"])

        router = CompressionStrategyRouter(scheduler=_FixedScheduler())
        snap = _make_snapshot("x" * 800)
        snap.query = "What changed?"
        snap.token_budget = 32

        output = await router.route_and_compress(snap, _ctx())

        compressor.assert_awaited_once()
        assert compressor.await_args.kwargs["token_budget"] == 32
        assert compressor.await_args.kwargs["query"] == "What changed?"
        assert output.output_type == OutputType.COMPRESSED
        assert "compressed answer" in output.content

    async def test_router_injects_llm_adapter_into_default_strategies(self):
        llm = object()

        CompressionStrategyRouter(llm_adapter=llm)
        registry = StrategyRegistry.instance()

        assert registry.get("qa")._llm is llm
        assert registry.get("task")._llm is llm
        assert registry.get("long_session")._llm is llm
        assert registry.get("compaction")._llm is llm
