"""Context aggregator (UC001).

Concurrently gathers context from multiple sources within a 200ms deadline:
  - Long-term memory (LTM) search
  - Working memory notes
  - JIT-resolved refs
  - Tool context items

Results are merged, deduplicated, scored, and truncated to token budget.

Supports two retrieval modes:
  - fast   (default): single query, parallel retrieval via HybridRetriever
  - quality          : agentic LLM-driven retrieval via AgenticRetriever for
                       complex multi-step tasks (higher latency, better recall)

Supports L0/L1/L2 progressive context expansion:
  - ABSTRACT (~100 tokens): loaded first for all candidates
  - OVERVIEW (~2k tokens): loaded for high-scoring candidates when budget allows
  - DETAIL  (unlimited): loaded on demand for the top candidates
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

from context_agent.adapters.ltm_adapter import LongTermMemoryPort
from context_agent.config.defaults import AGGREGATION_TIMEOUT_MS, DEFAULT_TOKEN_BUDGET
from context_agent.core.context.jit_resolver import JITResolver
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.models.context import (
    ContextItem,
    ContextLevel,
    ContextSnapshot,
    MemoryCategory,
)
from context_agent.models.ref import ContextRef
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)


@dataclass
class AggregationRequest:
    """Input specification for a context aggregation run."""

    scope_id: str
    session_id: str
    query: str
    refs: list[ContextRef] = field(default_factory=list)
    token_budget: int = DEFAULT_TOKEN_BUDGET
    top_k: int = 10
    enable_ltm: bool = True
    enable_working_memory: bool = True
    timeout_ms: float = AGGREGATION_TIMEOUT_MS
    extra_metadata: dict = field(default_factory=dict)
    # Dual-path retrieval mode (adapted from OpenViking find/search)
    mode: Literal["fast", "quality"] = "fast"
    # Maximum content detail level to inject (L0/L1/L2 progressive expansion)
    max_level: ContextLevel = ContextLevel.DETAIL
    # Semantic category filter — None means no filter (all categories)
    category_filter: list[MemoryCategory] | None = None


class ContextAggregator:
    """Aggregates context from multiple sources in parallel."""

    def __init__(
        self,
        ltm: LongTermMemoryPort | None = None,
        working_memory: WorkingMemoryManager | None = None,
        jit_resolver: JITResolver | None = None,
    ) -> None:
        self._ltm = ltm
        self._wm = working_memory
        self._jit = jit_resolver

    async def aggregate(self, request: AggregationRequest) -> ContextSnapshot:
        """Gather and merge context from all sources into a single snapshot."""
        async with traced_span(
            "context_aggregator.aggregate",
            {
                "scope_id": request.scope_id,
                "query_len": len(request.query),
                "mode": request.mode,
                "max_level": request.max_level,
            },
        ):
            t0 = time.monotonic()

            # ── Source retrieval ────────────────────────────────────────────
            tasks: list[asyncio.Task] = []
            labels: list[str] = []

            if request.enable_ltm and self._ltm is not None:
                if request.mode == "quality":
                    # Quality path: use agentic LLM-driven retrieval when available
                    tasks.append(asyncio.create_task(
                        self._ltm_quality_search(request)
                    ))
                else:
                    tasks.append(asyncio.create_task(
                        self._ltm.search(request.scope_id, request.query, request.top_k)
                    ))
                labels.append("ltm")

            if request.enable_working_memory and self._wm is not None:
                tasks.append(asyncio.create_task(
                    self._wm.to_context_items(request.scope_id, request.session_id)
                ))
                labels.append("working_memory")

            if request.refs and self._jit is not None:
                tasks.append(asyncio.create_task(
                    self._jit.resolve_batch(request.refs, top_k=request.top_k)
                ))
                labels.append("jit_refs")

            timeout = request.timeout_ms / 1000
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "aggregation timeout",
                    scope_id=request.scope_id,
                    timeout_ms=request.timeout_ms,
                )
                results = []

            all_items: list[ContextItem] = []
            degraded: list[str] = []
            for label, result in zip(labels, results or []):
                if isinstance(result, Exception):
                    logger.warning("source failed", source=label, error=str(result))
                    degraded.append(label)
                else:
                    all_items.extend(result or [])

            # ── Category filter (MemoryCategory 6-taxonomy) ─────────────────
            if request.category_filter:
                all_items = self._apply_category_filter(all_items, request.category_filter)

            # ── L0/L1/L2 progressive expansion ──────────────────────────────
            all_items = self._apply_level_filter(all_items, request.max_level)

            # ── Dedup, sort, budget ──────────────────────────────────────────
            deduplicated = self._deduplicate(all_items)
            sorted_items = sorted(deduplicated, key=lambda x: x.score, reverse=True)
            budgeted = self._apply_token_budget(sorted_items, request.token_budget)

            total_tokens = sum(len(i.content) // 4 for i in budgeted)
            latency = record_latency(t0)

            logger.info(
                "context aggregated",
                scope_id=request.scope_id,
                items=len(budgeted),
                tokens=total_tokens,
                latency_ms=f"{latency:.1f}",
                mode=request.mode,
                max_level=request.max_level,
            )

            return ContextSnapshot(
                scope_id=request.scope_id,
                session_id=request.session_id,
                items=budgeted,
                total_tokens=total_tokens,
                token_budget=request.token_budget,
                query=request.query,
                degraded_sources=degraded,
            )

    async def _ltm_quality_search(
        self, request: AggregationRequest
    ) -> list[ContextItem]:
        """Quality-path LTM search. Falls back to standard search if agentic is unavailable."""
        try:
            if hasattr(self._ltm, "agentic_search"):
                return await self._ltm.agentic_search(  # type: ignore[attr-defined]
                    request.scope_id, request.query, request.top_k
                )
        except Exception as exc:
            logger.warning(
                "agentic search unavailable, falling back to standard",
                error=str(exc),
            )
        return await self._ltm.search(request.scope_id, request.query, request.top_k)

    @staticmethod
    def _apply_category_filter(
        items: list[ContextItem], category_filter: list[MemoryCategory]
    ) -> list[ContextItem]:
        """Retain only items whose category matches the filter (or have no category)."""
        allowed = set(category_filter)
        return [
            item for item in items
            if item.category is None or item.category in allowed
        ]

    @staticmethod
    def _apply_level_filter(
        items: list[ContextItem], max_level: ContextLevel
    ) -> list[ContextItem]:
        """Retain only items at or below the requested detail level.

        Level order: ABSTRACT < OVERVIEW < DETAIL
        """
        level_order = {
            ContextLevel.ABSTRACT: 0,
            ContextLevel.OVERVIEW: 1,
            ContextLevel.DETAIL: 2,
        }
        max_order = level_order[max_level]
        return [
            item for item in items
            if level_order.get(item.level, 2) <= max_order
        ]

    @staticmethod
    def _deduplicate(items: list[ContextItem]) -> list[ContextItem]:
        """Remove duplicate items by content hash, keeping highest-scored."""
        seen: dict[str, ContextItem] = {}
        for item in items:
            key = item.item_id
            if key not in seen or item.score > seen[key].score:
                seen[key] = item
        return list(seen.values())

    @staticmethod
    def _apply_token_budget(
        items: list[ContextItem], token_budget: int
    ) -> list[ContextItem]:
        """Greedily select items until token budget is reached."""
        result = []
        used = 0
        for item in items:
            tokens = len(item.content) // 4
            if used + tokens > token_budget:
                break
            result.append(item)
            used += tokens
        return result
