"""Tests for openJiuwen LTM adapter compatibility layers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.models.context import MemoryType


@pytest.mark.asyncio
async def test_openjiuwen_adapter_uses_official_search_signature():
    calls = {}

    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.3):
            calls.update(
                query=query,
                num=num,
                user_id=user_id,
                scope_id=scope_id,
                threshold=threshold,
            )
            return [
                SimpleNamespace(
                    mem_info=SimpleNamespace(
                        mem_id="mem-1",
                        content="hello",
                        type="semantic",
                    ),
                    score=0.91,
                )
            ]

    adapter = OpenJiuwenLTMAdapter(FakeLTM())
    results = await adapter.search("scope-1", "hello", top_k=3)

    assert calls == {
        "query": "hello",
        "num": 3,
        "user_id": "scope-1",
        "scope_id": "scope-1",
        "threshold": 0.3,
    }
    assert len(results) == 1
    assert results[0].memory_type == MemoryType.SEMANTIC
    assert results[0].metadata["memory_id"] == "mem-1"


@pytest.mark.asyncio
async def test_openjiuwen_adapter_delete_and_update_use_official_argument_names():
    delete_calls = {}
    update_calls = {}

    class FakeLTM:
        async def delete_mem_by_id(self, mem_id, user_id, scope_id):
            delete_calls.update(mem_id=mem_id, user_id=user_id, scope_id=scope_id)

        async def update_mem_by_id(self, mem_id, memory, user_id, scope_id):
            update_calls.update(mem_id=mem_id, memory=memory, user_id=user_id, scope_id=scope_id)

    adapter = OpenJiuwenLTMAdapter(FakeLTM())
    await adapter.delete_by_id("scope-1", "mem-1")
    await adapter.update_by_id("scope-1", "mem-1", {"content": "updated"})

    assert delete_calls == {"mem_id": "mem-1", "user_id": "scope-1", "scope_id": "scope-1"}
    assert update_calls == {
        "mem_id": "mem-1",
        "memory": "updated",
        "user_id": "scope-1",
        "scope_id": "scope-1",
    }


@pytest.mark.asyncio
async def test_openjiuwen_adapter_delete_failure_uses_memory_write_error():
    class FakeLTM:
        async def delete_mem_by_id(self, mem_id, user_id, scope_id):
            raise RuntimeError("delete boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with pytest.raises(AdapterError) as exc_info:
        await adapter.delete_by_id("scope-1", "mem-1")

    assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED


@pytest.mark.asyncio
async def test_openjiuwen_adapter_update_failure_uses_memory_write_error():
    class FakeLTM:
        async def update_mem_by_id(self, mem_id, memory, user_id, scope_id):
            raise RuntimeError("update boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with pytest.raises(AdapterError) as exc_info:
        await adapter.update_by_id("scope-1", "mem-1", {"content": "updated"})

    assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED


@pytest.mark.asyncio
async def test_openjiuwen_adapter_health_check_logs_debug_on_failure():
    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.0):
            raise RuntimeError("health boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with patch("context_agent.adapters.ltm_adapter.logger.debug") as debug:
        ok = await adapter.health_check()

    assert ok is False
    debug.assert_called_once()
