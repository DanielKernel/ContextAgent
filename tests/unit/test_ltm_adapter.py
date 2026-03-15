"""Tests for openJiuwen LTM adapter compatibility layers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from context_agent.models.context import MemoryType
from context_agent.utils.errors import AdapterError, ErrorCode


@pytest.mark.asyncio
async def test_openjiuwen_adapter_uses_official_search_signature() -> None:
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
async def test_openjiuwen_adapter_search_handles_unknown_memory_type() -> None:
    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.3):
            return [
                SimpleNamespace(
                    mem_info=SimpleNamespace(
                        mem_id="mem-2",
                        content="hello",
                        type="unknown-type",
                    ),
                    score=0.5,
                )
            ]

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    results = await adapter.search("scope-1", "hello", top_k=1)

    assert results[0].memory_type is None


@pytest.mark.asyncio
async def test_openjiuwen_adapter_delete_and_update_use_official_argument_names() -> None:
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
async def test_openjiuwen_adapter_delete_failure_uses_memory_write_error() -> None:
    class FakeLTM:
        async def delete_mem_by_id(self, mem_id, user_id, scope_id):
            raise RuntimeError("delete boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with pytest.raises(AdapterError) as exc_info:
        await adapter.delete_by_id("scope-1", "mem-1")

    assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED


@pytest.mark.asyncio
async def test_openjiuwen_adapter_update_failure_uses_memory_write_error() -> None:
    class FakeLTM:
        async def update_mem_by_id(self, mem_id, memory, user_id, scope_id):
            raise RuntimeError("update boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with pytest.raises(AdapterError) as exc_info:
        await adapter.update_by_id("scope-1", "mem-1", {"content": "updated"})

    assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED


@pytest.mark.asyncio
async def test_openjiuwen_adapter_health_check_logs_debug_on_failure() -> None:
    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.0):
            raise RuntimeError("health boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with patch("context_agent.adapters.ltm_adapter.logger.debug") as debug:
        ok = await adapter.health_check()

    assert ok is False
    debug.assert_called_once()


@pytest.mark.asyncio
async def test_openjiuwen_adapter_health_check_prefers_cleanup_resource_probe() -> None:
    class FakeResource:
        async def health_check(self) -> bool:
            return True

    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.0):
            raise AssertionError("search probe should not be used when a cleanup resource can health check")

    adapter = OpenJiuwenLTMAdapter(FakeLTM(), cleanup_resources=[FakeResource()])

    assert await adapter.health_check() is True


@pytest.mark.asyncio
async def test_openjiuwen_adapter_add_messages_uses_memory_config_flags() -> None:
    calls = {}

    class FakeLTM:
        async def add_messages(self, messages, agent_config, user_id, scope_id, session_id):
            calls["messages"] = messages
            calls["user_id"] = user_id
            calls["scope_id"] = scope_id
            calls["session_id"] = session_id
            calls["agent_config"] = agent_config

    adapter = OpenJiuwenLTMAdapter(
        FakeLTM(),
        memory_config={
            "enable_long_term_mem": False,
            "enable_user_profile": False,
            "enable_semantic_memory": True,
            "enable_episodic_memory": False,
            "enable_summary_memory": True,
        },
    )

    await adapter.add_messages(
        "scope-1",
        [{"role": "user", "content": "hello"}],
        session_id="session-9",
        user_id="user-1",
    )

    assert calls["user_id"] == "user-1"
    assert calls["scope_id"] == "scope-1"
    assert calls["session_id"] == "session-9"
    assert calls["agent_config"].enable_long_term_mem is False
    assert calls["agent_config"].enable_user_profile is False
    assert calls["agent_config"].enable_semantic_memory is True
    assert calls["agent_config"].enable_episodic_memory is False
    assert calls["agent_config"].enable_summary_memory is True


@pytest.mark.asyncio
async def test_openjiuwen_adapter_add_messages_without_agent_config_support() -> None:
    calls = {}

    class FakeLTM:
        async def add_messages(self, messages, user_id, scope_id, session_id):
            calls["messages"] = messages
            calls["user_id"] = user_id
            calls["scope_id"] = scope_id
            calls["session_id"] = session_id

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    await adapter.add_messages(
        "scope-1",
        [{"role": "assistant", "content": "hello"}],
        session_id="session-9",
    )

    assert calls["messages"] == [{"role": "assistant", "content": "hello"}]
    assert calls["user_id"] == "scope-1"
    assert calls["scope_id"] == "scope-1"
    assert calls["session_id"] == "session-9"


@pytest.mark.asyncio
async def test_openjiuwen_adapter_add_messages_failure_uses_memory_write_error() -> None:
    class FakeLTM:
        async def add_messages(self, messages, user_id, scope_id, session_id):
            raise RuntimeError("add boom")

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    with pytest.raises(AdapterError) as exc_info:
        await adapter.add_messages("scope-1", [{"role": "user", "content": "hello"}])

    assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED


@pytest.mark.asyncio
async def test_openjiuwen_adapter_health_check_returns_true_on_success() -> None:
    class FakeLTM:
        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.0):
            return []

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    assert await adapter.health_check() is True


@pytest.mark.asyncio
async def test_openjiuwen_adapter_agentic_search_uses_agentic_retrieve() -> None:
    class FakeLTM:
        async def agentic_retrieve(self, query, user_id, top_k):
            return [SimpleNamespace(id="mem-3", memory="agentic", score=0.9)]

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    results = await adapter.agentic_search("scope-1", "hello", top_k=2)

    assert len(results) == 1
    assert results[0].content == "agentic"
    assert results[0].metadata["retrieval_mode"] == "agentic"


@pytest.mark.asyncio
async def test_openjiuwen_adapter_agentic_search_falls_back_to_standard_search() -> None:
    class FakeLTM:
        async def agentic_retrieve(self, query, user_id, top_k):
            raise RuntimeError("agentic boom")

        async def search_user_mem(self, query, num, user_id, scope_id, threshold=0.3):
            return [
                SimpleNamespace(
                    mem_info=SimpleNamespace(
                        mem_id="mem-4",
                        content="fallback",
                        type="semantic",
                    ),
                    score=0.8,
                )
            ]

    adapter = OpenJiuwenLTMAdapter(FakeLTM())

    results = await adapter.agentic_search("scope-1", "hello", top_k=1)

    assert len(results) == 1
    assert results[0].content == "fallback"


@pytest.mark.asyncio
async def test_openjiuwen_adapter_close_disposes_cleanup_resources() -> None:
    calls: list[str] = []

    class FakeResource:
        async def dispose(self) -> None:
            calls.append("resource.dispose")

    class FakeLTM:
        async def close(self) -> None:
            calls.append("ltm.close")

    adapter = OpenJiuwenLTMAdapter(
        FakeLTM(),
        cleanup_resources=[FakeResource()],
    )

    await adapter.close()

    assert calls == ["resource.dispose", "ltm.close"]
