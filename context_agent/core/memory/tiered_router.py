"""Tiered memory router (UC002).

Routes memory retrieval across hot (Redis/in-memory), warm (openJiuwen LTM),
and cold (external memory) tiers based on latency budget and memory type.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import redis.asyncio as aioredis
from pydantic import ValidationError
from redis.exceptions import RedisError

from context_agent.adapters.external_memory_adapter import ExternalMemoryPort
from context_agent.adapters.ltm_adapter import LongTermMemoryPort
from context_agent.config.settings import get_settings
from context_agent.models.context import ContextItem, MemoryType
from context_agent.utils.errors import AdapterError, RetrievalError
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)

# Only VARIABLE type memory is cached in the hot tier (ADR-004)
_HOT_TIER_MEMORY_TYPES = {MemoryType.VARIABLE}


def _validate_hot_cache_payload(
    payload: object,
    *,
    scope_id: str,
    cache_source: str,
) -> list[dict[str, Any]] | None:
    if not isinstance(payload, list):
        logger.warning(
            "hot tier cache payload invalid",
            scope_id=scope_id,
            cache_source=cache_source,
            payload_type=type(payload).__name__,
        )
        return None

    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            logger.warning(
                "hot tier cache entry invalid",
                scope_id=scope_id,
                cache_source=cache_source,
                entry_index=index,
                entry_type=type(entry).__name__,
            )
            return None
        try:
            item = ContextItem(**entry)
        except ValidationError as exc:
            logger.warning(
                "hot tier cache entry failed validation",
                scope_id=scope_id,
                cache_source=cache_source,
                entry_index=index,
                error=str(exc),
            )
            return None
        if item.memory_type not in _HOT_TIER_MEMORY_TYPES:
            logger.warning(
                "hot tier cache entry rejected",
                scope_id=scope_id,
                cache_source=cache_source,
                entry_index=index,
                memory_type=str(item.memory_type),
            )
            return None
        validated.append(entry)
    return validated


def _validate_local_hot_items(
    items: object,
    *,
    scope_id: str,
) -> list[ContextItem] | None:
    if not isinstance(items, list):
        logger.warning(
            "hot tier local cache payload invalid",
            scope_id=scope_id,
            payload_type=type(items).__name__,
        )
        return None

    for index, item in enumerate(items):
        if not isinstance(item, ContextItem):
            logger.warning(
                "hot tier local cache entry invalid",
                scope_id=scope_id,
                entry_index=index,
                entry_type=type(item).__name__,
            )
            return None
        if item.memory_type not in _HOT_TIER_MEMORY_TYPES:
            logger.warning(
                "hot tier local cache entry rejected",
                scope_id=scope_id,
                entry_index=index,
                memory_type=str(item.memory_type),
            )
            return None
    return items


class TieredMemoryRouter:
    """Routes memory queries across hot / warm / cold tiers.

    Hot tier  (<20ms)  : Redis KV or in-memory dict
    Warm tier (<100ms) : openJiuwen LongTermMemory (LTM)
    Cold tier (<300ms) : External memory backends (vector DB, knowledge base)
    """

    def __init__(
        self,
        ltm: LongTermMemoryPort,
        external: ExternalMemoryPort | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._ltm = ltm
        self._external = external
        self._redis = redis_client
        # Fallback in-process KV when Redis unavailable
        self._local_cache: dict[str, tuple[list[ContextItem], float]] = {}
        self._settings = get_settings()

    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int | None = None,
        memory_types: list[MemoryType] | None = None,
        filters: dict[str, Any] | None = None,
        latency_budget_ms: float = 300.0,
    ) -> tuple[list[ContextItem], dict[str, float]]:
        """Search across tiers and return items + per-tier latency breakdown.

        Returns:
            (items, latency_breakdown) where latency_breakdown keys are 'hot', 'warm', 'cold'.
        """
        effective_top_k = top_k or self._settings.retrieval_default_top_k
        remaining_budget = latency_budget_ms
        results: list[ContextItem] = []
        latencies: dict[str, float] = {"hot": 0.0, "warm": 0.0, "cold": 0.0}

        async with traced_span("tiered_memory_router.search", {"scope_id": scope_id}):
            # ── Hot tier ────────────────────────────────────────────────────
            hot_types = memory_types or list(MemoryType)
            if any(t in _HOT_TIER_MEMORY_TYPES for t in hot_types):
                t0 = time.monotonic()
                hot_items = await self._hot_search(scope_id, query, effective_top_k)
                latencies["hot"] = record_latency(t0)
                results.extend(hot_items)
                remaining_budget -= latencies["hot"]
                logger.debug(
                    "hot tier search",
                    scope_id=scope_id,
                    hits=len(hot_items),
                    latency_ms=f"{latencies['hot']:.1f}",
                )

            if len(results) >= effective_top_k or remaining_budget <= 0:
                return results[:effective_top_k], latencies

            # ── Warm tier ───────────────────────────────────────────────────
            t0 = time.monotonic()
            warm_items = await self._warm_search(
                scope_id,
                query,
                effective_top_k - len(results),
                memory_types,
                filters,
                remaining_budget,
            )
            latencies["warm"] = record_latency(t0)
            results.extend(warm_items)
            remaining_budget -= latencies["warm"]

            if len(results) >= effective_top_k or remaining_budget <= 0 or self._external is None:
                return results[:effective_top_k], latencies

            # ── Cold tier ───────────────────────────────────────────────────
            t0 = time.monotonic()
            cold_items = await self._cold_search(
                scope_id,
                query,
                effective_top_k - len(results),
                filters,
                remaining_budget,
            )
            latencies["cold"] = record_latency(t0)
            results.extend(cold_items)

        return results[:effective_top_k], latencies

    # ── Hot tier ─────────────────────────────────────────────────────────────

    async def _hot_search(
        self, scope_id: str, query: str, top_k: int
    ) -> list[ContextItem]:
        cache_key = f"ca:hot:{scope_id}"
        try:
            timeout = self._settings.hot_tier_timeout_ms / 1000
            if self._redis is not None:
                raw = await asyncio.wait_for(self._redis.get(cache_key), timeout=timeout)
                if raw:
                    data = json.loads(raw)
                    validated = _validate_hot_cache_payload(
                        data,
                        scope_id=scope_id,
                        cache_source="redis",
                    )
                    if validated is not None:
                        return [ContextItem(**entry) for entry in validated[:top_k]]
            else:
                entry = self._local_cache.get(cache_key)
                if entry and time.monotonic() - entry[1] < self._settings.hot_tier_ttl_s:
                    validated = _validate_local_hot_items(entry[0], scope_id=scope_id)
                    if validated is not None:
                        return validated[:top_k]
                    self._local_cache.pop(cache_key, None)
        except TimeoutError as exc:
            logger.debug("hot tier miss/error", scope_id=scope_id, error=str(exc))
        except (RedisError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning("hot tier cache read failed", scope_id=scope_id, error=str(exc))
        return []

    async def warm_cache(
        self, scope_id: str, items: list[ContextItem], ttl_s: int | None = None
    ) -> None:
        """Pre-warm hot tier with items (called by AsyncMemoryProcessor after updates)."""
        cache_key = f"ca:hot:{scope_id}"
        effective_ttl = ttl_s or self._settings.hot_tier_ttl_s
        data = [
            item.model_dump(mode="json")
            for item in items
            if item.memory_type in _HOT_TIER_MEMORY_TYPES
        ]
        if not data:
            return
        try:
            if self._redis is not None:
                await self._redis.setex(cache_key, effective_ttl, json.dumps(data))
            else:
                local_items = [item for item in items if item.memory_type in _HOT_TIER_MEMORY_TYPES]
                self._local_cache[cache_key] = (local_items, time.monotonic())
        except Exception as exc:
            logger.warning("hot tier warm failed", scope_id=scope_id, error=str(exc))

    # ── Warm tier ─────────────────────────────────────────────────────────────

    async def _warm_search(
        self,
        scope_id: str,
        query: str,
        top_k: int,
        memory_types: list[MemoryType] | None,
        filters: dict[str, Any] | None,
        budget_ms: float,
    ) -> list[ContextItem]:
        timeout = min(budget_ms / 1000, self._settings.warm_tier_timeout_ms / 1000)
        try:
            items = await asyncio.wait_for(
                self._ltm.search(scope_id, query, top_k, memory_types, filters),
                timeout=timeout,
            )
            for item in items:
                item.tier = "warm"
            return items
        except TimeoutError:
            logger.warning("warm tier timeout", scope_id=scope_id, budget_ms=budget_ms)
            return []
        except AdapterError as exc:
            logger.warning("warm tier error", scope_id=scope_id, error=str(exc))
            return []

    # ── Cold tier ─────────────────────────────────────────────────────────────

    async def _cold_search(
        self,
        scope_id: str,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None,
        budget_ms: float,
    ) -> list[ContextItem]:
        if self._external is None:
            return []
        timeout = min(budget_ms / 1000, self._settings.cold_tier_timeout_ms / 1000)
        try:
            items = await asyncio.wait_for(
                self._external.search(scope_id, query, top_k, filters),
                timeout=timeout,
            )
            for item in items:
                item.tier = "cold"
            return items
        except TimeoutError:
            logger.warning("cold tier timeout", scope_id=scope_id, budget_ms=budget_ms)
            return []
        except (AdapterError, RetrievalError) as exc:
            logger.warning("cold tier error", scope_id=scope_id, error=str(exc))
            return []

    # ── Usage feedback ─────────────────────────────────────────────────────────

    async def record_usage(self, scope_id: str, item_ids: list[str]) -> None:
        """Record that specific context items were confirmed as useful by the caller.

        Increments active_count on matching hot-tier cache entries so that
        Hotness Score boosts them in future retrievals.

        Args:
            scope_id: Scope whose cache to update.
            item_ids: IDs of items that were actually used in a model call.
        """
        if not item_ids:
            return
        id_set = set(item_ids)

        # Update hot-tier Redis entries
        cache_key = f"ca:hot:{scope_id}"
        try:
            if self._redis is not None:
                raw = await self._redis.get(cache_key)
                if raw:
                    data = json.loads(raw)
                    validated = _validate_hot_cache_payload(
                        data,
                        scope_id=scope_id,
                        cache_source="redis",
                    )
                    if validated is None:
                        return
                    changed = False
                    for entry in validated:
                        if entry.get("item_id") in id_set:
                            entry["active_count"] = entry.get("active_count", 0) + 1
                            changed = True
                    if changed:
                        await self._redis.setex(
                            cache_key,
                            self._settings.hot_tier_ttl_s,
                            json.dumps(validated),
                        )
            else:
                # Update in-process cache
                entry = self._local_cache.get(cache_key)
                if entry:
                    items, ts = entry
                    validated = _validate_local_hot_items(items, scope_id=scope_id)
                    if validated is None:
                        self._local_cache.pop(cache_key, None)
                        return
                    for item in items:
                        if item.item_id in id_set:
                            item.active_count += 1
                    self._local_cache[cache_key] = (items, ts)
        except (RedisError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning("record_usage failed", scope_id=scope_id, error=str(exc))
