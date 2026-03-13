"""Functional tests for JITResolver — covers all RefType dispatch paths."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import context_agent.core.context.jit_resolver as jit_resolver_module
from context_agent.core.context.jit_resolver import JITResolver
from context_agent.models.context import ContextItem
from context_agent.models.ref import ContextRef, RefType


def _make_ref(ref_type: RefType, locator: str = "test-locator") -> ContextRef:
    return ContextRef(ref_type=ref_type, scope_id="scope1", locator=locator)


def _make_items(n: int = 2) -> list[ContextItem]:
    return [ContextItem(source_type="ltm", content=f"result-{i}") for i in range(n)]


def _mock_retriever(items=None):
    r = AsyncMock()
    r.agentic_search = AsyncMock(return_value=items or _make_items())
    r.graph_search = AsyncMock(return_value=items or _make_items())
    return r


@pytest.mark.asyncio
class TestJITResolver:
    async def test_vector_ref_calls_agentic_search(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = _make_ref(RefType.VECTOR, "embed_abc")
        items = await resolver.resolve(ref)
        retriever.agentic_search.assert_awaited_once_with("scope1", "embed_abc", "embed_abc", 5)
        assert len(items) == 2

    async def test_graph_ref_calls_graph_search(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = _make_ref(RefType.GRAPH, "entity:123")
        items = await resolver.resolve(ref)
        retriever.graph_search.assert_awaited_once_with("scope1", "entity:123")
        assert len(items) == 2

    async def test_memory_ref_calls_agentic_search(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = _make_ref(RefType.MEMORY, "mem:abc")
        items = await resolver.resolve(ref)
        retriever.agentic_search.assert_awaited()

    async def test_scratchpad_ref_resolves_via_working_memory(self):
        retriever = _mock_retriever(items=[])
        wm = AsyncMock()
        note_mock = MagicMock()
        note_mock.note_id = "n1"
        note_mock.note_type = "plan"
        note_mock.content = {"current_task": "analyse pricing"}
        wm.get_note = AsyncMock(return_value=note_mock)

        resolver = JITResolver(retriever=retriever, working_memory=wm)
        ref = _make_ref(RefType.SCRATCHPAD, "sess1:n1")
        items = await resolver.resolve(ref)
        assert len(items) == 1
        assert "analyse pricing" in items[0].content

    async def test_expired_ref_returns_empty(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = ContextRef(
            ref_type=RefType.VECTOR,
            scope_id="scope1",
            locator="stale",
            expires_at=time.time() - 1,
        )
        items = await resolver.resolve(ref)
        assert items == []
        retriever.agentic_search.assert_not_awaited()

    async def test_local_cache_hit(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = _make_ref(RefType.VECTOR, "cached-query")

        # First call populates cache
        items1 = await resolver.resolve(ref)
        assert len(items1) == 2

        # Second call should use cache (retriever not called again)
        items2 = await resolver.resolve(ref)
        assert retriever.agentic_search.await_count == 1  # still 1, not 2
        assert len(items2) == 2

    async def test_batch_resolve(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        refs = [_make_ref(RefType.VECTOR, f"q{i}") for i in range(5)]
        items = await resolver.resolve_batch(refs, top_k=3)
        assert len(items) == 10  # 5 refs × 2 items each

    async def test_store_and_resolve_tool_result(self):
        retriever = _mock_retriever(items=[])
        resolver = JITResolver(retriever=retriever)
        item = ContextItem(source_type="tool_result", content="calc result: 42")
        await resolver.store_tool_result("scope1", "calc:op1", item)

        ref = _make_ref(RefType.TOOL_RESULT, "calc:op1")
        resolved = await resolver.resolve(ref)
        assert len(resolved) == 1
        assert "42" in resolved[0].content

    async def test_file_ref_calls_agentic_search(self):
        retriever = _mock_retriever()
        resolver = JITResolver(retriever=retriever)
        ref = _make_ref(RefType.FILE, "/docs/architecture.md")
        await resolver.resolve(ref)
        retriever.agentic_search.assert_awaited()

    async def test_local_tool_result_cache_expires(self, monkeypatch):
        retriever = _mock_retriever(items=[])
        resolver = JITResolver(retriever=retriever)
        clock = {"now": 1000.0}
        monkeypatch.setattr(jit_resolver_module.time, "monotonic", lambda: clock["now"])

        await resolver.store_tool_result(
            "scope1",
            "calc:ttl",
            ContextItem(source_type="tool_result", content="expiring"),
            ttl_s=1,
        )

        clock["now"] = 1000.5
        fresh = await resolver.resolve(_make_ref(RefType.TOOL_RESULT, "calc:ttl"))
        assert len(fresh) == 1

        clock["now"] = 1001.5
        expired = await resolver.resolve(_make_ref(RefType.TOOL_RESULT, "calc:ttl"))
        assert expired == []

    async def test_local_cache_prunes_to_max_entries(self, monkeypatch):
        retriever = _mock_retriever(items=[])
        resolver = JITResolver(retriever=retriever)
        resolver._settings.jit_cache_local_max_entries = 2
        clock = {"now": 2000.0}
        monkeypatch.setattr(jit_resolver_module.time, "monotonic", lambda: clock["now"])

        for index in range(3):
            await resolver.store_tool_result(
                "scope1",
                f"calc:{index}",
                ContextItem(source_type="tool_result", content=f"value-{index}"),
                ttl_s=60,
            )
            clock["now"] += 1

        assert len(resolver._local_cache) == 2
        assert "ca:tool:scope1:calc:0" not in resolver._local_cache

    async def test_store_tool_result_uses_configured_default_ttl(self):
        retriever = _mock_retriever(items=[])
        resolver = JITResolver(retriever=retriever)
        resolver._settings.jit_cache_ttl_s = 123
        resolver._set_local_cache = MagicMock()

        await resolver.store_tool_result(
            "scope1",
            "calc:cfg-ttl",
            ContextItem(source_type="tool_result", content="configured ttl"),
        )

        resolver._set_local_cache.assert_called_once()
        assert resolver._set_local_cache.call_args.args[2] == 123
