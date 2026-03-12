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
from typing import Any

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
        working_memory: Any | None = None,
        memory_orchestrator: Any | None = None,
        memory_processor: Any | None = None,
        tiered_router: Any | None = None,
        tool_governor: Any | None = None,
    ) -> None:
        self._aggregator = aggregator
        self._compression = compression_router or CompressionStrategyRouter()
        self._ec = exposure_controller or ExposureController()
        self._hc = health_checker
        self._vm = version_manager or ContextVersionManager()
        self._scheduler = scheduler or HybridStrategyScheduler()
        self._working_memory = working_memory
        self._memory_orchestrator = memory_orchestrator
        self._memory_processor = memory_processor
        self._tiered_router = tiered_router
        self._tool_governor = tool_governor

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
        mode: str = "fast",
        category_filter: list | None = None,
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
            from context_agent.models.context import ContextLevel, MemoryCategory
            agg_request = AggregationRequest(
                scope_id=scope_id,
                session_id=session_id,
                query=query,
                refs=refs or [],
                token_budget=token_budget,
                top_k=top_k,
                mode=mode,  # type: ignore[arg-type]
                category_filter=category_filter,
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
                    token_budget=token_budget,
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

    async def mark_used(
        self, scope_id: str, session_id: str, item_ids: list[str]
    ) -> int:
        """Increment active_count on context items confirmed as useful.

        Updates both the tiered router hot-cache and working-memory entries.
        Returns the total number of records updated.
        """
        updated = 0
        if self._tiered_router is not None:
            await self._tiered_router.record_usage(scope_id, item_ids)
        if self._working_memory is not None:
            updated += await self._working_memory.mark_used(scope_id, session_id, item_ids)
        return updated

    def record_tool_result(
        self,
        scope_id: str,
        tool_id: str,
        success: bool,
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Delegate tool call outcome recording to ToolContextGovernor."""
        if self._tool_governor is not None:
            self._tool_governor.record_tool_result(
                tool_id=tool_id,
                success=success,
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

    async def ingest_messages(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        user_id: str = "",
        persist_long_term: bool = True,
    ) -> int:
        """Persist conversation messages into working memory and openJiuwen LTM."""
        if self._memory_orchestrator is not None:
            return await self._memory_orchestrator.ingest_messages(
                scope_id=scope_id,
                session_id=session_id,
                messages=messages,
                user_id=user_id,
                persist_long_term=persist_long_term,
            )

        if self._working_memory is None:
            return 0

        from context_agent.models.context import ContextItem, MemoryType

        count = 0
        for message in messages:
            content = str(message.get("content", "")).strip()
            role = str(message.get("role", "user")).strip() or "user"
            if not content:
                continue
            await self._working_memory.write(
                scope_id=scope_id,
                session_id=session_id,
                item=ContextItem(
                    scope_id=scope_id,
                    session_id=session_id,
                    source_type=role,
                    memory_type=MemoryType.VARIABLE,
                    content=f"[{role}] {content}",
                    metadata={**message.get("metadata", {}), "role": role},
                ),
            )
            count += 1
        return count
