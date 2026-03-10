"""Functional tests for ContextVersionManager."""

from __future__ import annotations

import pytest

from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextItem, ContextSnapshot
from context_agent.utils.errors import ContextAgentError


def _make_snapshot(scope: str = "s1", session: str = "sess1", n_items: int = 3) -> ContextSnapshot:
    snap = ContextSnapshot(scope_id=scope, session_id=session, query="test query")
    for i in range(n_items):
        snap.add_item(ContextItem(source_type="ltm", content=f"item content {i}", score=0.9))
    snap.total_tokens = n_items * 10
    return snap


@pytest.mark.asyncio
class TestContextVersionManager:
    async def test_create_snapshot_returns_record(self):
        vm = ContextVersionManager()
        snap = _make_snapshot()
        record = await vm.create_snapshot(snap, label="test-label", created_by="pytest")
        assert record.version_id
        assert record.label == "test-label"
        assert record.item_count == 3
        assert record.token_count == 30
        assert record.scope_id == "s1"

    async def test_restore_returns_original_snapshot(self):
        vm = ContextVersionManager()
        snap = _make_snapshot()
        record = await vm.create_snapshot(snap)

        restored = await vm.restore("s1", "sess1", record.version_id)
        assert restored.scope_id == snap.scope_id
        assert restored.session_id == snap.session_id
        assert len(restored.items) == len(snap.items)
        assert restored.query == "test query"

    async def test_restore_nonexistent_raises(self):
        vm = ContextVersionManager()
        with pytest.raises(ContextAgentError, match="not found"):
            await vm.restore("s1", "sess1", "nonexistent-id")

    async def test_list_versions_newest_first(self):
        vm = ContextVersionManager()
        snap = _make_snapshot()
        r1 = await vm.create_snapshot(snap, label="v1")
        r2 = await vm.create_snapshot(snap, label="v2")
        r3 = await vm.create_snapshot(snap, label="v3")

        records = await vm.list_versions("s1", "sess1")
        assert records[0].label == "v3"  # newest first

    async def test_list_versions_scope_isolated(self):
        vm = ContextVersionManager()
        snap_a = _make_snapshot(scope="scope-a", session="sess1")
        snap_b = _make_snapshot(scope="scope-b", session="sess1")

        await vm.create_snapshot(snap_a, label="a1")
        await vm.create_snapshot(snap_b, label="b1")

        records_a = await vm.list_versions("scope-a", "sess1")
        records_b = await vm.list_versions("scope-b", "sess1")

        assert len(records_a) == 1
        assert len(records_b) == 1
        assert records_a[0].label == "a1"

    async def test_delete_version(self):
        vm = ContextVersionManager()
        snap = _make_snapshot()
        record = await vm.create_snapshot(snap)

        await vm.delete_version(record.version_id)
        # After delete, restore should fail
        with pytest.raises(ContextAgentError):
            await vm.restore("s1", "sess1", record.version_id)

    async def test_list_versions_limit(self):
        vm = ContextVersionManager()
        snap = _make_snapshot()
        for i in range(10):
            await vm.create_snapshot(snap, label=f"v{i}")

        records = await vm.list_versions("s1", "sess1", limit=5)
        assert len(records) == 5
