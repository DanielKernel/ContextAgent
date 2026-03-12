"""Compression strategy router (UC009).

Routes a ContextSnapshot to the appropriate CompressionStrategy
determined by the HybridStrategyScheduler, applies the compression,
and returns a ContextOutput ready for injection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySchedule,
    StrategySelectionContext,
)
from context_agent.strategies.registry import (
    StrategyRegistry,
    ensure_default_strategies_registered,
)
from context_agent.utils.errors import ContextAgentError, ErrorCode, StrategyNotFoundError
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)


class CompressionStrategyRouter:
    """Applies the best available compression strategy to a ContextSnapshot."""

    def __init__(self, scheduler: HybridStrategyScheduler | None = None) -> None:
        ensure_default_strategies_registered()
        self._scheduler = scheduler or HybridStrategyScheduler()
        self._registry = StrategyRegistry.instance()

    async def route_and_compress(
        self,
        snapshot: ContextSnapshot,
        ctx: StrategySelectionContext,
    ) -> ContextOutput:
        """Select a strategy, compress the snapshot, and return an output."""
        async with traced_span(
            "compression_router.route",
            {"scope_id": snapshot.scope_id, "tokens": snapshot.total_tokens},
        ):
            schedule = self._scheduler.schedule(ctx)
            return await self._apply_schedule(snapshot, schedule)

    async def _apply_schedule(
        self,
        snapshot: ContextSnapshot,
        schedule: StrategySchedule,
    ) -> ContextOutput:
        t0 = time.monotonic()
        last_error: Exception | None = None

        for strategy_id in schedule.strategy_ids:
            try:
                strategy = self._registry.get(strategy_id)
            except StrategyNotFoundError as exc:
                logger.warning("strategy not found", strategy_id=strategy_id)
                last_error = exc
                continue

            try:
                output = await strategy.compress(snapshot)
                latency = record_latency(t0)
                logger.info(
                    "compression applied",
                    scope_id=snapshot.scope_id,
                    strategy=strategy_id,
                    original_tokens=snapshot.total_tokens,
                    output_tokens=output.token_count,
                    latency_ms=f"{latency:.1f}",
                )
                return output
            except Exception as exc:
                logger.warning(
                    "compression failed, trying next strategy",
                    strategy=strategy_id,
                    error=str(exc),
                )
                last_error = exc

        # All strategies failed — return raw concatenation as fallback
        logger.warning(
            "all strategies failed, using raw fallback",
            scope_id=snapshot.scope_id,
            error=str(last_error),
        )
        return self._raw_fallback(snapshot)

    @staticmethod
    def _raw_fallback(snapshot: ContextSnapshot) -> ContextOutput:
        text = "\n\n".join(item.content for item in snapshot.items)
        return ContextOutput(
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            output_type=OutputType.RAW,
            content=text,
            token_count=len(text) // 4,
        )
