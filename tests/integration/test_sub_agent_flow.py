"""Integration tests: sub-agent delegation and context merge flow."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextItem, ContextSnapshot, MemoryType
from context_agent.models.policy import ExposurePolicy
from context_agent.orchestration.sub_agent_manager import SubAgentContextManager


def _make_parent_snapshot(
    scope_id: str = "parent",
    session_id: str = "main",
) -> ContextSnapshot:
    snap = ContextSnapshot(scope_id=scope_id, session_id=session_id, query="planning task")
    snap.add_item(ContextItem(
        source_type="ltm", content="Project deadline: Q4 2025",
        memory_type=MemoryType.EPISODIC, score=0.95,
    ))
    snap.add_item(ContextItem(
        source_type="ltm", content="Team budget: $100k",
        memory_type=MemoryType.VARIABLE, score=0.88,
    ))
    snap.add_item(ContextItem(
        source_type="tool_result", content="CONFIDENTIAL: salary bands",
        metadata={"tool_id": "hr_system"}, score=0.75,
    ))
    snap.total_tokens = sum(len(i.content) // 4 for i in snap.items)
    return snap


@pytest.mark.asyncio
class TestSubAgentDelegationFlow:
    async def test_delegation_creates_child_scope(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        view, ticket = await manager.delegate(snap, "Research competitors")

        assert ticket.parent_scope_id == "parent"
        assert ticket.child_scope_id.startswith("parent:child:")
        assert ticket.task_description == "Research competitors"
        assert not ticket.is_expired

    async def test_default_policy_passes_all_items(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        view, ticket = await manager.delegate(snap, "Full context task", policy=None)

        # Default policy is permissive
        assert len(view.visible_items) == 3

    async def test_restrictive_policy_filters_confidential(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        policy = ExposurePolicy(
            scope_id="parent",
            allowed_source_types=["ltm"],  # exclude tool_result
        )
        view, ticket = await manager.delegate(snap, "Market research", policy=policy)

        assert len(view.visible_items) == 2
        assert view.hidden_item_count == 1
        contents = [i.content for i in view.visible_items]
        assert not any("CONFIDENTIAL" in c for c in contents)

    async def test_result_merge_tags_items(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        _, ticket = await manager.delegate(snap, "Analysis task")

        result_items = [
            ContextItem(source_type="analysis", content="Competitor charges 20% less.")
        ]
        merged = await manager.receive_result(ticket, result_items)

        assert len(merged) == 1
        assert merged[0].metadata.get("ticket_id") == ticket.ticket_id
        assert merged[0].metadata.get("delegated_from") == ticket.child_scope_id

    async def test_expired_ticket_merge_returns_empty(self):
        import time
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        _, ticket = await manager.delegate(snap, "Quick task", ttl_s=0.001)

        await __import__("asyncio").sleep(0.01)  # let it expire

        result_items = [ContextItem(source_type="analysis", content="late result")]
        merged = await manager.receive_result(ticket, result_items)
        assert merged == []

    async def test_version_created_on_delegation(self):
        vm = ContextVersionManager()
        manager = SubAgentContextManager(
            version_manager=vm
        )
        snap = _make_parent_snapshot()
        _, ticket = await manager.delegate(snap, "Versioned task")

        # Check version was stored
        records = await vm.list_versions("parent", "main")
        assert len(records) == 1
        assert "pre-delegation" in records[0].label

    async def test_get_active_tickets(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()

        _, t1 = await manager.delegate(snap, "Task 1")
        _, t2 = await manager.delegate(snap, "Task 2")

        active = manager.get_active_tickets("parent")
        assert len(active) == 2

    async def test_ticket_removed_after_result_received(self):
        manager = SubAgentContextManager()
        snap = _make_parent_snapshot()
        _, ticket = await manager.delegate(snap, "Short task")

        await manager.receive_result(ticket, [])
        active = manager.get_active_tickets("parent")
        assert len(active) == 0

    async def test_multi_level_delegation(self):
        """Parent → child → grandchild scoping."""
        manager = SubAgentContextManager()
        parent_snap = _make_parent_snapshot(scope_id="root")

        child_view, child_ticket = await manager.delegate(parent_snap, "Child task")

        # Build child snapshot from view
        child_snap = ContextSnapshot(
            scope_id=child_ticket.child_scope_id,
            session_id="child-sess",
            items=child_view.visible_items,
        )
        # Delegate further to grandchild
        grandchild_view, grandchild_ticket = await manager.delegate(
            child_snap, "Grandchild task"
        )
        assert grandchild_ticket.parent_scope_id == child_ticket.child_scope_id
        assert grandchild_ticket.child_scope_id != child_ticket.child_scope_id
