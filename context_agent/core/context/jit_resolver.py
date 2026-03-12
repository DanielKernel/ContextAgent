"""JIT context resolver (UC004).

Resolves lightweight ContextRef objects into actual ContextItems on demand,
enabling just-in-time retrieval without pre-loading all candidate information.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from pydantic import ValidationError
from redis.exceptions import RedisError

from context_agent.adapters.retriever_adapter import RetrieverPort
from context_agent.config.defaults import (
    JIT_LOCAL_CACHE_MAX_ENTRIES,
    JIT_RESULT_CACHE_TTL_S,
)
from context_agent.models.context import ContextItem
from context_agent.models.ref import ContextRef, RefType
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import record_latency, traced_span

logger = get_logger(__name__)


@dataclass
class _LocalCacheEntry:
    items: list[ContextItem]
    created_at: float
    ttl_s: int

    def is_expired(self, now: float) -> bool:
        return now - self.created_at >= self.ttl_s


class JITResolver:
    """Resolves ContextRef objects to ContextItems just-in-time.

    Routing:
      VECTOR       → RetrieverPort.agentic_search (vector index)
      GRAPH        → RetrieverPort.graph_search
      MEMORY       → RetrieverPort.agentic_search (memory locator)
      SCRATCHPAD   → WorkingMemoryManager.get_note (injected at construction)
      TOOL_RESULT  → hot-tier KV cache lookup
      FILE         → RetrieverPort.agentic_search (file path locator)
      OBJECT       → RetrieverPort.agentic_search (object key locator)
    """

    def __init__(
        self,
        retriever: RetrieverPort,
        working_memory: Any | None = None,  # WorkingMemoryManager
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._retriever = retriever
        self._wm = working_memory
        self._redis = redis_client
        self._local_cache: dict[str, _LocalCacheEntry] = {}

    async def resolve(
        self,
        ref: ContextRef,
        top_k: int = 5,
    ) -> list[ContextItem]:
        """Resolve a single ContextRef to a list of ContextItems."""
        if ref.is_expired:
            logger.debug("ref expired, skipping", ref_id=ref.ref_id, ref_type=ref.ref_type)
            return []

        async with traced_span(
            "jit_resolver.resolve",
            {"ref_type": ref.ref_type, "scope_id": ref.scope_id},
        ):
            # Check resolution cache first
            cached = await self._get_cache(ref.ref_id)
            if cached is not None:
                return cached

            t0 = time.monotonic()
            items = await self._dispatch(ref, top_k)
            latency = record_latency(t0)

            logger.debug(
                "jit resolved",
                ref_type=ref.ref_type,
                scope_id=ref.scope_id,
                items=len(items),
                latency_ms=f"{latency:.1f}",
            )

            # Cache the result
            await self._set_cache(ref.ref_id, items)
            return items

    async def resolve_batch(
        self,
        refs: list[ContextRef],
        top_k: int = 5,
        max_concurrency: int = 5,
    ) -> list[ContextItem]:
        """Resolve multiple refs concurrently with a concurrency limit."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _resolve_one(ref: ContextRef) -> list[ContextItem]:
            async with semaphore:
                try:
                    return await self.resolve(ref, top_k)
                except Exception as exc:
                    logger.warning("ref resolution failed", ref_id=ref.ref_id, error=str(exc))
                    return []

        results = await asyncio.gather(*[_resolve_one(r) for r in refs])
        return [item for sublist in results for item in sublist]

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, ref: ContextRef, top_k: int) -> list[ContextItem]:
        scope_id = ref.scope_id
        locator = ref.locator

        if ref.ref_type == RefType.VECTOR:
            return await self._retriever.agentic_search(scope_id, locator, locator, top_k)

        elif ref.ref_type == RefType.GRAPH:
            return await self._retriever.graph_search(scope_id, locator)

        elif ref.ref_type == RefType.MEMORY:
            return await self._retriever.agentic_search(scope_id, locator, locator, top_k)

        elif ref.ref_type == RefType.SCRATCHPAD:
            return await self._resolve_scratchpad(ref, scope_id)

        elif ref.ref_type == RefType.TOOL_RESULT:
            return await self._resolve_tool_result(locator, scope_id)

        elif ref.ref_type in (RefType.FILE, RefType.OBJECT):
            return await self._retriever.agentic_search(scope_id, locator, locator, top_k)

        logger.warning("unknown ref_type", ref_type=ref.ref_type)
        return []

    async def _resolve_scratchpad(self, ref: ContextRef, scope_id: str) -> list[ContextItem]:
        if self._wm is None:
            return []
        try:
            # locator format: "{session_id}:{note_id}"
            parts = ref.locator.split(":", 1)
            session_id, note_id = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
            note = await self._wm.get_note(scope_id, session_id, note_id)
            return [
                ContextItem(
                    source_type="scratchpad",
                    tier="hot",
                    score=1.0,
                    content=json.dumps(note.content, ensure_ascii=False),
                    metadata={"note_type": note.note_type, "note_id": note.note_id},
                )
            ]
        except Exception as exc:
            logger.warning("scratchpad resolution failed", error=str(exc))
            return []

    async def _resolve_tool_result(self, cache_key: str, scope_id: str) -> list[ContextItem]:
        full_key = f"ca:tool:{scope_id}:{cache_key}"
        try:
            if self._redis is not None:
                raw = await self._redis.get(full_key)
            else:
                cached = self._get_local_cache(full_key)
                return cached[:1] if cached is not None else []

            if raw:
                data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                return [ContextItem(**data) if isinstance(data, dict) else ContextItem(
                    source_type="tool_result", tier="hot", content=str(data)
                )]
        except (RedisError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning("tool result resolution failed", error=str(exc))
        return []

    async def store_tool_result(
        self, scope_id: str, cache_key: str, item: ContextItem, ttl_s: int = JIT_RESULT_CACHE_TTL_S
    ) -> None:
        """Store a tool result in the JIT cache for later resolution."""
        full_key = f"ca:tool:{scope_id}:{cache_key}"
        try:
            if self._redis is not None:
                await self._redis.setex(full_key, ttl_s, item.model_dump_json())
            else:
                self._set_local_cache(full_key, [item], ttl_s)
        except (RedisError, TypeError, ValueError) as exc:
            logger.warning("tool result store failed", error=str(exc))

    # ── Cache helpers ─────────────────────────────────────────────────────────

    async def _get_cache(self, ref_id: str) -> list[ContextItem] | None:
        cache_key = f"ca:jit:{ref_id}"
        try:
            if self._redis is not None:
                raw = await self._redis.get(cache_key)
                if raw:
                    return [ContextItem(**d) for d in json.loads(raw)]
            else:
                return self._get_local_cache(cache_key)
        except (RedisError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning("jit cache read failed", ref_id=ref_id, error=str(exc))
        return None

    async def _set_cache(self, ref_id: str, items: list[ContextItem]) -> None:
        cache_key = f"ca:jit:{ref_id}"
        try:
            if self._redis is not None:
                await self._redis.setex(
                    cache_key,
                    JIT_RESULT_CACHE_TTL_S,
                    json.dumps([i.model_dump(mode="json") for i in items]),
                )
            else:
                self._set_local_cache(cache_key, items, JIT_RESULT_CACHE_TTL_S)
        except (RedisError, TypeError, ValueError) as exc:
            logger.warning("jit cache write failed", ref_id=ref_id, error=str(exc))

    def _get_local_cache(self, cache_key: str) -> list[ContextItem] | None:
        now = time.monotonic()
        self._prune_local_cache(now)
        entry = self._local_cache.get(cache_key)
        if entry is None:
            return None
        if entry.is_expired(now):
            self._local_cache.pop(cache_key, None)
            return None
        return entry.items

    def _set_local_cache(self, cache_key: str, items: list[ContextItem], ttl_s: int) -> None:
        now = time.monotonic()
        self._prune_local_cache(now)
        self._local_cache[cache_key] = _LocalCacheEntry(
            items=items,
            created_at=now,
            ttl_s=ttl_s,
        )
        self._prune_local_cache(now)

    def _prune_local_cache(self, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        expired_keys = [
            key for key, entry in self._local_cache.items() if entry.is_expired(current_time)
        ]
        for key in expired_keys:
            self._local_cache.pop(key, None)

        overflow = len(self._local_cache) - JIT_LOCAL_CACHE_MAX_ENTRIES
        if overflow <= 0:
            return

        oldest_keys = sorted(
            self._local_cache,
            key=lambda key: self._local_cache[key].created_at,
        )[:overflow]
        for key in oldest_keys:
            self._local_cache.pop(key, None)
