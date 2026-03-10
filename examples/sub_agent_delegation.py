"""Example: sub-agent delegation with context scoping.

Demonstrates how a parent agent delegates a task to a child agent
with filtered context, then merges the result back.

Run:
    python examples/sub_agent_delegation.py
"""

from __future__ import annotations

import asyncio

from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextItem, ContextSnapshot, MemoryType
from context_agent.models.policy import ExposurePolicy
from context_agent.orchestration.sub_agent_manager import SubAgentContextManager
from context_agent.utils.logging import configure_logging, get_logger

configure_logging("INFO")
logger = get_logger(__name__)


def _build_parent_snapshot() -> ContextSnapshot:
    """Create a realistic parent agent snapshot."""
    snap = ContextSnapshot(scope_id="parent-agent", session_id="main-session")
    snap.add_item(ContextItem(
        source_type="ltm",
        content="Task: Analyse competitor pricing data for Q4 planning.",
        memory_type=MemoryType.EPISODIC,
        score=0.95,
    ))
    snap.add_item(ContextItem(
        source_type="ltm",
        content="Budget: $50,000 per quarter for infrastructure.",
        memory_type=MemoryType.VARIABLE,
        score=0.88,
    ))
    snap.add_item(ContextItem(
        source_type="tool_result",
        content="CONFIDENTIAL: Internal salary bands document.",
        metadata={"tool_id": "internal_hr_tool"},
        score=0.70,
    ))
    snap.total_tokens = sum(len(i.content) // 4 for i in snap.items)
    return snap


async def main() -> None:
    # Parent snapshot has 3 items, one of which is confidential
    parent_snapshot = _build_parent_snapshot()

    print(f"\n👤 Parent agent context: {len(parent_snapshot.items)} items")
    for item in parent_snapshot.items:
        print(f"   - [{item.source_type}] {item.content[:60]}")

    # Policy: child agent can only see public LTM — not tool results
    policy = ExposurePolicy(
        scope_id="parent-agent",
        allowed_source_types=["ltm"],  # exclude tool_result
    )

    manager = SubAgentContextManager(
        exposure_controller=ExposureController(),
        version_manager=ContextVersionManager(),
    )

    # Delegate
    child_view, ticket = await manager.delegate(
        parent_snapshot,
        task_description="Research competitor pricing data",
        policy=policy,
        ttl_s=60.0,
    )

    print(f"\n🤖 Child agent view (ticket={ticket.ticket_id[:8]}…):")
    print(f"   Visible items: {len(child_view.visible_items)}")
    print(f"   Hidden items: {child_view.hidden_item_count}")
    for item in child_view.visible_items:
        print(f"   - [{item.source_type}] {item.content[:60]}")

    # Simulate child agent producing a result
    result_items = [
        ContextItem(
            source_type="tool_result",
            content="Competitor analysis: Company X charges 20% less.",
            score=0.90,
        )
    ]

    # Merge result back to parent
    merged = await manager.receive_result(ticket, result_items)

    print(f"\n✅ Merged {len(merged)} result items back to parent scope")
    for item in merged:
        print(f"   - {item.content}")
        print(f"     (delegated_from={item.metadata.get('delegated_from', '?')[:20]}…)")


if __name__ == "__main__":
    asyncio.run(main())
