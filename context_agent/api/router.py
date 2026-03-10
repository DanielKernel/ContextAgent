"""ContextAPIRouter — unified facade (UC007).

Routes incoming ContextRequests to the correct pipeline based on OutputType:
  - COMPRESSED  → aggregate + compress
  - RAW         → aggregate only
  - STRUCTURED  → aggregate + compression with structured JSON output
  - SNAPSHOT    → create a version snapshot and return version info
"""

from __future__ import annotations

import time
import uuid

from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.health_checker import ContextHealthChecker
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType
from context_agent.models.policy import ExposurePolicy
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.context_aggregator import (
    AggregationRequest,
    ContextAggregator,
)
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySelectionContext,
)
from context_agent.utils.errors import ContextAgentError
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)


class ContextAPIRouter:
    """Unified facade that orchestrates the full context pipeline."""

    def __init__(
        self,
        aggregator: ContextAggregator,
        compression_router: CompressionStrategyRouter | None = None,
        exposure_controller: ExposureController | None = None,
        health_checker: ContextHealthChecker | None = None,
        version_manager: ContextVersionManager | None = None,
        scheduler: HybridStrategyScheduler | None = None,
    ) -> None:
        self._aggregator = aggregator
        self._compression = compression_router or CompressionStrategyRouter()
        self._ec = exposure_controller or ExposureController()
        self._hc = health_checker
        self._vm = version_manager or ContextVersionManager()
        self._scheduler = scheduler or HybridStrategyScheduler()

    async def handle(
        self,
        scope_id: str,
        session_id: str,
        query: str,
        output_type: OutputType = OutputType.COMPRESSED,
        token_budget: int = 4096,
        top_k: int = 10,
        task_type: str = "",
        agent_role: str = "",
        refs: list | None = None,
        policy: ExposurePolicy | None = None,
    ) -> tuple[ContextOutput, list[str]]:
        """Execute the full context pipeline and return (output, warnings)."""
        request_id = uuid.uuid4().hex
        warnings: list[str] = []

        async with traced_span(
            "api_router.handle",
            {
                "scope_id": scope_id,
                "output_type": output_type,
                "request_id": request_id,
            },
        ):
            t0 = time.monotonic()

            # 1. Aggregate
            agg_request = AggregationRequest(
                scope_id=scope_id,
                session_id=session_id,
                query=query,
                refs=refs or [],
                token_budget=token_budget,
                top_k=top_k,
            )
            snapshot = await self._aggregator.aggregate(agg_request)

            # 2. Apply exposure policy
            if policy is not None:
                view = await self._ec.apply(snapshot, policy)
                # Rebuild snapshot with only visible items
                snapshot = ContextSnapshot(
                    scope_id=snapshot.scope_id,
                    session_id=snapshot.session_id,
                    items=view.visible_items,
                    total_tokens=sum(len(i.content) // 4 for i in view.visible_items),
                    query=snapshot.query,
                )
                if view.hidden_item_count > 0:
                    warnings.append(
                        f"ExposurePolicy filtered {view.hidden_item_count} items."
                    )

            # 3. Health check (background — non-blocking)
            if self._hc is not None:
                health = await self._hc.quick_check(snapshot)
                if not health.is_healthy:
                    for issue in health.issues:
                        warnings.append(f"Health: {issue.description}")

            # 4. Route to output type
            if output_type == OutputType.RAW:
                output = self._build_raw_output(snapshot)

            elif output_type == OutputType.SNAPSHOT:
                version = await self._vm.create_snapshot(
                    snapshot, label=f"api:{query[:32]}"
                )
                output = ContextOutput(
                    scope_id=scope_id,
                    session_id=session_id,
                    output_type=OutputType.SNAPSHOT,
                    content=version.version_id,
                    token_count=snapshot.total_tokens,
                )

            else:  # COMPRESSED or STRUCTURED
                ctx = StrategySelectionContext(
                    scope_id=scope_id,
                    task_type=task_type,
                    agent_role=agent_role,
                    token_used=snapshot.total_tokens,
                    token_budget=token_budget,
                )
                if output_type == OutputType.STRUCTURED:
                    ctx.task_type = ctx.task_type or "compaction"
                output = await self._compression.route_and_compress(snapshot, ctx)

            latency = record_latency(t0)
            logger.info(
                "api handled",
                scope_id=scope_id,
                output_type=output_type,
                tokens=output.token_count,
                latency_ms=f"{latency:.1f}",
                warnings=len(warnings),
            )
            return output, warnings

    @staticmethod
    def _build_raw_output(snapshot: ContextSnapshot) -> ContextOutput:
        text = "\n\n".join(i.content for i in snapshot.items)
        return ContextOutput(
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            output_type=OutputType.RAW,
            content=text,
            token_count=len(text) // 4,
        )
