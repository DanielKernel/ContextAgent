"""Unit tests for TieredMemoryRouter (UC002)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from context_agent.core.memory.tiered_router import TieredMemoryRouter
from context_agent.models.context import ContextItem, MemoryType


def _item(content: str, memory_type: MemoryType) -> ContextItem:
    return ContextItem(
        source_type="ltm",
        content=content,
        memory_type=memory_type,
        score=0.9,
    )


@pytest.mark.asyncio
class TestTieredMemoryRouter:
    async def test_hot_tier_hit_short_circuits_lower_tiers(self):
        ltm = AsyncMock()
        external = AsyncMock()
        router = TieredMemoryRouter(ltm=ltm, external=external)

        hot_item = _item("recent session state", MemoryType.VARIABLE)
        await router.warm_cache("scope-1", [hot_item])

        items, latencies = await router.search(
            "scope-1",
            "recent state",
            top_k=1,
            memory_types=[MemoryType.VARIABLE],
        )

        assert len(items) == 1
        assert items[0].content == "recent session state"
        assert latencies["hot"] >= 0.0
        ltm.search.assert_not_awaited()
        external.search.assert_not_awaited()

    async def test_warm_and_cold_tiers_fill_remaining_budget(self):
        warm_item = _item("warm memory", MemoryType.SEMANTIC)
        cold_item = _item("cold knowledge", MemoryType.SEMANTIC)

        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[warm_item])
        external = AsyncMock()
        external.search = AsyncMock(return_value=[cold_item])

        router = TieredMemoryRouter(ltm=ltm, external=external)

        items, latencies = await router.search(
            "scope-1",
            "customer history",
            top_k=2,
            memory_types=[MemoryType.SEMANTIC],
        )

        assert [item.content for item in items] == ["warm memory", "cold knowledge"]
        assert items[0].tier == "warm"
        assert items[1].tier == "cold"
        assert latencies["warm"] >= 0.0
        assert latencies["cold"] >= 0.0
        ltm.search.assert_awaited_once()
        external.search.assert_awaited_once()

    async def test_warm_timeout_skips_cold_when_budget_exhausted(self):
        async def _slow_search(*args, **kwargs):
            await asyncio.sleep(0.02)
            return [_item("slow warm result", MemoryType.SEMANTIC)]

        ltm = AsyncMock()
        ltm.search = AsyncMock(side_effect=_slow_search)
        external = AsyncMock()
        external.search = AsyncMock(return_value=[_item("cold result", MemoryType.SEMANTIC)])

        router = TieredMemoryRouter(ltm=ltm, external=external)

        items, _ = await router.search(
            "scope-1",
            "slow query",
            top_k=2,
            memory_types=[MemoryType.SEMANTIC],
            latency_budget_ms=1.0,
        )

        assert items == []
        external.search.assert_not_awaited()

    async def test_record_usage_updates_hot_cache_active_count(self):
        ltm = AsyncMock()
        router = TieredMemoryRouter(ltm=ltm)

        hot_item = _item("mutable state", MemoryType.VARIABLE)
        await router.warm_cache("scope-1", [hot_item])
        await router.record_usage("scope-1", [hot_item.item_id])

        items, _ = await router.search(
            "scope-1",
            "mutable",
            top_k=1,
            memory_types=[MemoryType.VARIABLE],
        )

        assert items[0].active_count == 1

    async def test_invalid_redis_hot_cache_payload_falls_back_to_warm(self):
        warm_item = _item("warm fallback", MemoryType.VARIABLE)
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[warm_item])
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=json.dumps({"invalid": "payload"}))

        router = TieredMemoryRouter(ltm=ltm, redis_client=redis_client)

        items, _ = await router.search(
            "scope-1",
            "recent state",
            top_k=1,
            memory_types=[MemoryType.VARIABLE],
        )

        assert [item.content for item in items] == ["warm fallback"]
        ltm.search.assert_awaited_once()

    async def test_hot_cache_rejects_non_variable_memory_types(self):
        warm_item = _item("warm variable fallback", MemoryType.VARIABLE)
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[warm_item])
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(
            return_value=json.dumps(
                [
                    _item("semantic item", MemoryType.SEMANTIC).model_dump(mode="json"),
                ]
            )
        )

        router = TieredMemoryRouter(ltm=ltm, redis_client=redis_client)

        items, _ = await router.search(
            "scope-1",
            "recent state",
            top_k=1,
            memory_types=[MemoryType.VARIABLE],
        )

        assert [item.content for item in items] == ["warm variable fallback"]
        ltm.search.assert_awaited_once()
