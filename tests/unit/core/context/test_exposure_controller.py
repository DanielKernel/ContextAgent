"""Unit tests for ExposureController."""

from __future__ import annotations

import pytest

from context_agent.core.context.exposure_controller import ExposureController
from context_agent.models.context import ContextItem, ContextSnapshot, MemoryType
from context_agent.models.policy import ExposurePolicy


def _make_snapshot(items: list[ContextItem]) -> ContextSnapshot:
    snap = ContextSnapshot(scope_id="scope1", session_id="sess1")
    for item in items:
        snap.add_item(item)
    return snap


@pytest.mark.asyncio
class TestExposureController:
    async def test_allow_all_with_default_policy(self):
        ec = ExposureController()
        items = [
            ContextItem(source_type="ltm", content="a"),
            ContextItem(source_type="tool_result", content="b"),
            ContextItem(source_type="scratchpad", content="c"),
        ]
        snap = _make_snapshot(items)
        policy = await ec.get_default_policy("scope1")
        view = await ec.apply(snap, policy)
        assert len(view.visible_items) == 3
        assert view.hidden_item_count == 0

    async def test_restrict_source_type(self):
        ec = ExposureController()
        items = [
            ContextItem(source_type="ltm", content="keep"),
            ContextItem(source_type="tool_result", content="filter out"),
        ]
        snap = _make_snapshot(items)
        policy = ExposurePolicy(scope_id="scope1", allowed_source_types=["ltm"])
        view = await ec.apply(snap, policy)
        assert len(view.visible_items) == 1
        assert view.visible_items[0].content == "keep"
        assert view.hidden_item_count == 1

    async def test_state_only_fields_excluded(self):
        ec = ExposureController()
        items = [
            ContextItem(source_type="tool_result", content="hidden"),
            ContextItem(source_type="ltm", content="visible"),
        ]
        snap = _make_snapshot(items)
        policy = ExposurePolicy(scope_id="scope1", state_only_fields=["tool_result"])
        view = await ec.apply(snap, policy)
        assert len(view.visible_items) == 1
        assert view.visible_items[0].source_type == "ltm"

    async def test_scratchpad_field_gate(self):
        ec = ExposureController()
        items = [
            ContextItem(
                source_type="scratchpad",
                content="allowed note",
                metadata={"field_name": "current_task"},
            ),
            ContextItem(
                source_type="scratchpad",
                content="blocked note",
                metadata={"field_name": "private_data"},
            ),
        ]
        snap = _make_snapshot(items)
        policy = ExposurePolicy(
            scope_id="scope1",
            allowed_scratchpad_fields=["current_task"],
        )
        view = await ec.apply(snap, policy)
        assert len(view.visible_items) == 1
        assert view.visible_items[0].content == "allowed note"

    async def test_tool_gate(self):
        ec = ExposureController()
        items = [
            ContextItem(
                source_type="tool_result",
                content="allowed",
                metadata={"tool_id": "calculator"},
            ),
            ContextItem(
                source_type="tool_result",
                content="blocked",
                metadata={"tool_id": "web_search"},
            ),
        ]
        snap = _make_snapshot(items)
        policy = ExposurePolicy(scope_id="scope1", allowed_tool_ids=["calculator"])
        view = await ec.apply(snap, policy)
        assert len(view.visible_items) == 1
        assert view.visible_items[0].content == "allowed"

    async def test_policy_id_recorded_in_view(self):
        ec = ExposureController()
        snap = _make_snapshot([ContextItem(source_type="ltm", content="x")])
        policy = ExposurePolicy(scope_id="scope1")
        view = await ec.apply(snap, policy)
        assert view.applied_policy_id == policy.policy_id
