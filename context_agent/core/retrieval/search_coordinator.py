"""Unified search coordinator (UC012).

Orchestrates multi-path parallel retrieval:
  - Vector + sparse hybrid (HybridRetriever)
  - Graph relation (GraphRetriever)
  - LTM memory search (LongTermMemoryPort)
  - Hierarchy / prefix search (lightweight filter)
Fuses results via RRF, applies reranking, and enforces token budget.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any

from context_agent.adapters.ltm_adapter import LongTermMemoryPort
from context_agent.adapters.retriever_adapter import RetrieverPort
from context_agent.config.defaults import (
    DEFAULT_TOP_K,
    HYBRID_SPARSE_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
    RERANK_TOP_K,
)
from context_agent.core.memory.hotness import HOTNESS_ALPHA, compute_hotness
from context_agent.core.retrieval.task_conditioning import apply_task_conditioning
from context_agent.models.context import ContextItem
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)


@dataclass
class RetrievalPlan:
    """Configuration for a multi-path retrieval operation."""

    query: str
    scope_id: str
    task_type: str = ""
    agent_role: str = ""
    top_k: int = DEFAULT_TOP_K
    enable_hybrid: bool = True
    enable_graph: bool = False
    enable_ltm: bool = True
    enable_hierarchy: bool = False
    hierarchy_prefix: str = ""  # prefix filter for hierarchical search
    vector_weight: float = HYBRID_VECTOR_WEIGHT
    sparse_weight: float = HYBRID_SPARSE_WEIGHT
    rerank: bool = True
    rerank_top_k: int = RERANK_TOP_K
    timeout_ms: float = 250.0
    filters: dict[str, Any] = field(default_factory=dict)


class UnifiedSearchCoordinator:
    """Coordinates parallel multi-path retrieval with RRF fusion and reranking."""

    def __init__(
        self,
        retriever: RetrieverPort,
        ltm: LongTermMemoryPort | None = None,
    ) -> None:
        self._retriever = retriever
        self._ltm = ltm

    async def search(self, plan: RetrievalPlan) -> list[ContextItem]:
        """Execute retrieval plan and return fused, optionally reranked results."""
        async with traced_span("search_coordinator.search", {"scope_id": plan.scope_id}):
            t0 = time.monotonic()
            tasks: list[asyncio.Task[list[ContextItem]]] = []
            labels: list[str] = []

            if plan.enable_hybrid:
                tasks.append(asyncio.create_task(
                    self._retriever.hybrid_search(
                        plan.scope_id, plan.query, plan.top_k,
                        plan.vector_weight, plan.sparse_weight, plan.filters,
                    )
                ))
                labels.append("hybrid")

            if plan.enable_graph:
                tasks.append(asyncio.create_task(
                    self._retriever.graph_search(plan.scope_id, plan.query)
                ))
                labels.append("graph")

            if plan.enable_ltm and self._ltm is not None:
                tasks.append(asyncio.create_task(
                    self._ltm.search(plan.scope_id, plan.query, plan.top_k)
                ))
                labels.append("ltm")

            timeout = plan.timeout_ms / 1000
            try:
                raw_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning(
                    "search coordinator timeout",
                    scope_id=plan.scope_id,
                    timeout_ms=plan.timeout_ms,
                )
                raw_results = []

            # Collect successful results
            all_items: list[list[ContextItem]] = []
            for label, result in zip(labels, raw_results or [], strict=False):
                if isinstance(result, Exception):
                    logger.warning("retrieval path failed", path=label, error=str(result))
                    all_items.append([])
                else:
                    all_items.append(result)

            # Prefix filter for hierarchy search
            if plan.enable_hierarchy and plan.hierarchy_prefix:
                hierarchy_items = self._hierarchy_filter(all_items, plan.hierarchy_prefix)
                all_items.append(hierarchy_items)

            fused = self._rrf_fuse(all_items, top_k=plan.top_k * 2)

            if plan.rerank and fused:
                fused = await self._retriever.rerank(plan.query, fused, plan.rerank_top_k)

            fused = apply_task_conditioning(
                fused,
                task_type=plan.task_type,
                agent_role=plan.agent_role,
            )

            latency = record_latency(t0)
            logger.debug(
                "search complete",
                scope_id=plan.scope_id,
                results=len(fused),
                latency_ms=f"{latency:.1f}",
            )
            return fused[: plan.top_k]

    @staticmethod
    def _rrf_fuse(
        result_lists: list[list[ContextItem]],
        k: int = 60,
        top_k: int = 20,
    ) -> list[ContextItem]:
        """Reciprocal Rank Fusion across multiple result lists with hotness blending.

        RRF score = Σ 1/(k + rank + 1) across all result lists.
        Final score is blended with hotness at HOTNESS_ALPHA weight so that
        frequently-confirmed context items rank higher over time.
        """
        scores: dict[str, float] = {}
        item_map: dict[str, ContextItem] = {}

        for results in result_lists:
            for rank, item in enumerate(results):
                rrf_score = 1.0 / (k + rank + 1)
                scores[item.item_id] = scores.get(item.item_id, 0.0) + rrf_score
                item_map[item.item_id] = item

        sorted_ids = sorted(scores, key=lambda iid: scores[iid], reverse=True)
        result = []
        for iid in sorted_ids[:top_k]:
            item = item_map[iid].model_copy()
            rrf = scores[iid]
            hotness = compute_hotness(item.active_count, item.updated_at)
            # Normalise raw RRF score to [0,1] via tanh, then blend with hotness
            normalised_rrf = math.tanh(rrf * k)
            blended = (1.0 - HOTNESS_ALPHA) * normalised_rrf + HOTNESS_ALPHA * hotness
            item.score = min(1.0, blended)
            result.append(item)
        return result

    @staticmethod
    def _hierarchy_filter(
        all_items: list[list[ContextItem]], prefix: str
    ) -> list[ContextItem]:
        """Filter items whose metadata 'source' starts with the given prefix."""
        matches = []
        for item_list in all_items:
            for item in item_list:
                source = item.metadata.get("source", "")
                if str(source).startswith(prefix):
                    matches.append(item)
        return matches
