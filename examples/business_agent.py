"""Example: complete business agent integration with ContextAgent.

Demonstrates a realistic CRM support agent that uses ContextAgent as its
context backbone. The agent handles customer enquiries using:
  - Long-term customer memory (purchase history, preferences)
  - Working memory (current session notes)
  - Compressed context injection per turn
  - Tool-filtered context (only relevant tools exposed)
  - Sub-agent delegation for complex analysis

This example runs fully without openJiuwen using stub adapters.

Run:
    python examples/business_agent.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

from context_agent.api.router import ContextAPIRouter
from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.health_checker import ContextHealthChecker
from context_agent.core.context.jit_resolver import JITResolver
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.core.retrieval.tool_governor import ToolContextGovernor, ToolDefinition
from context_agent.models.context import (
    ContextItem, ContextOutput, MemoryType, OutputType,
)
from context_agent.models.policy import ExposurePolicy
from context_agent.models.ref import ContextRef, RefType
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.context_aggregator import (
    AggregationRequest, ContextAggregator,
)
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler, StrategySchedule, StrategySelectionContext,
)
from context_agent.orchestration.sub_agent_manager import SubAgentContextManager
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.registry import StrategyRegistry
from context_agent.utils.logging import configure_logging, get_logger

configure_logging("INFO")
logger = get_logger(__name__)

# ── Stub LTM with realistic CRM data ─────────────────────────────────────────

CUSTOMER_MEMORY = {
    "customer:C001": [
        ContextItem(
            source_type="ltm", memory_type=MemoryType.EPISODIC, score=0.95,
            content="Customer C001 (Alice Wang) purchased the Pro Plan on 2024-08-15. "
                    "Monthly spend: $299. Renewal date: 2025-08-15.",
        ),
        ContextItem(
            source_type="ltm", memory_type=MemoryType.PROCEDURAL, score=0.88,
            content="Alice prefers email communication over phone. "
                    "Response language: Simplified Chinese.",
        ),
        ContextItem(
            source_type="ltm", memory_type=MemoryType.EPISODIC, score=0.82,
            content="Previous ticket T-2024-0892: resolved billing discrepancy in Oct 2024. "
                    "Issue was a duplicate charge; refund of $299 issued.",
        ),
        ContextItem(
            source_type="ltm", memory_type=MemoryType.SEMANTIC, score=0.78,
            content="Alice's company: TechStart Inc. Industry: SaaS. Team size: 25. "
                    "Primary use case: AI-powered customer analytics.",
        ),
    ]
}


class CRMStubLTM:
    async def search(self, scope_id: str, query: str, top_k: int = 10) -> list[ContextItem]:
        # Simulate customer-scoped memory lookup
        items = CUSTOMER_MEMORY.get(scope_id, [])
        logger.debug("CRM LTM search", scope_id=scope_id, found=len(items))
        return items[:top_k]


# ── Support-optimised compression strategy ────────────────────────────────────

class SupportContextStrategy(CompressionStrategy):
    """Compresses context into a structured support briefing."""

    @property
    def strategy_id(self) -> str:
        return "support_briefing"

    async def compress(self, snapshot) -> ContextOutput:
        procedural = [i for i in snapshot.items if i.memory_type == MemoryType.PROCEDURAL]
        episodic = [i for i in snapshot.items if i.memory_type == MemoryType.EPISODIC]
        semantic = [i for i in snapshot.items if i.memory_type == MemoryType.SEMANTIC]
        other = [i for i in snapshot.items
                 if i.memory_type not in (MemoryType.PROCEDURAL, MemoryType.EPISODIC, MemoryType.SEMANTIC)]

        sections = []
        if procedural:
            sections.append("【客户偏好】\n" + "\n".join(f"• {i.content}" for i in procedural))
        if episodic:
            sections.append("【历史记录】\n" + "\n".join(f"• {i.content}" for i in episodic))
        if semantic:
            sections.append("【客户背景】\n" + "\n".join(f"• {i.content}" for i in semantic))
        if other:
            sections.append("【其他上下文】\n" + "\n".join(f"• {i.content}" for i in other))

        content = "\n\n".join(sections)
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=content,
            token_count=len(content) // 4,
        )

    def estimate_tokens(self, snapshot) -> int:
        return snapshot.total_tokens // 2


# ── Fixed scheduler for support task ─────────────────────────────────────────

class SupportScheduler(HybridStrategyScheduler):
    def schedule(self, ctx: StrategySelectionContext) -> StrategySchedule:
        return StrategySchedule(strategy_ids=["support_briefing"])


# ── Support tool definitions ──────────────────────────────────────────────────

SUPPORT_TOOLS = [
    ToolDefinition(
        tool_id="view_account", name="View Account",
        description="Retrieve full account details for a customer ID.",
        required_for_task_types=["support"],
    ),
    ToolDefinition(
        tool_id="lookup_ticket", name="Lookup Ticket",
        description="Retrieve a previous support ticket by ticket number.",
        required_for_task_types=["support"],
    ),
    ToolDefinition(
        tool_id="issue_refund", name="Issue Refund",
        description="Process a refund for a specific transaction.",
        required_for_task_types=["support"],
    ),
    ToolDefinition(
        tool_id="send_email", name="Send Email",
        description="Send a reply email to the customer.",
        required_for_task_types=["support", "communication"],
    ),
    ToolDefinition(
        tool_id="escalate_ticket", name="Escalate Ticket",
        description="Escalate to L2 support team with priority flag.",
        required_for_task_types=["support"],
    ),
    # These should NOT appear for support tasks
    ToolDefinition(
        tool_id="deploy_service", name="Deploy Service",
        description="Trigger a production deployment.",
        required_for_task_types=["ops"],
    ),
    ToolDefinition(
        tool_id="run_tests", name="Run Tests",
        description="Execute automated test suite.",
        required_for_task_types=["dev"],
    ),
]


# ── CRM Support Agent ─────────────────────────────────────────────────────────

@dataclass
class CustomerEnquiry:
    customer_id: str
    session_id: str
    message: str
    turn: int = 1


class CRMSupportAgent:
    """A support agent that uses ContextAgent for context management."""

    def __init__(self, context_router: ContextAPIRouter, tool_governor: ToolContextGovernor):
        self._ctx = context_router
        self._tools = tool_governor

    async def handle_enquiry(self, enquiry: CustomerEnquiry) -> dict[str, Any]:
        """Process a customer enquiry and return agent response context."""
        print(f"\n{'='*60}")
        print(f"🎯 Turn {enquiry.turn} | Customer: {enquiry.customer_id}")
        print(f"   Query: {enquiry.message}")
        print('='*60)

        # 1. Retrieve compressed context
        output, warnings = await self._ctx.handle(
            scope_id=enquiry.customer_id,
            session_id=enquiry.session_id,
            query=enquiry.message,
            output_type=OutputType.COMPRESSED,
            token_budget=2048,
            task_type="support",
        )

        # 2. Get relevant tools
        tool_items = await self._tools.get_tool_context_items(
            scope_id=enquiry.customer_id,
            task_description=enquiry.message,
            task_type="support",
            top_k=5,
        )

        print(f"\n📦 Context retrieved ({output.token_count} tokens):")
        print("-" * 40)
        print(output.content)

        print(f"\n🔧 Available tools ({len(tool_items)}):")
        for item in tool_items:
            print(f"   • {item.metadata.get('tool_id')}")

        if warnings:
            print(f"\n⚠️  Warnings: {warnings}")

        return {
            "context": output.content,
            "token_count": output.token_count,
            "tools": [t.metadata.get("tool_id") for t in tool_items],
            "warnings": warnings,
        }


# ── Setup & Run ───────────────────────────────────────────────────────────────

def setup_context_agent() -> tuple[ContextAPIRouter, ToolContextGovernor]:
    # Register strategies
    registry = StrategyRegistry.instance()
    if "support_briefing" not in registry.list():
        registry.register(SupportContextStrategy())

    # Wire components
    ltm = CRMStubLTM()
    aggregator = ContextAggregator(ltm=ltm)
    comp_router = CompressionStrategyRouter(scheduler=SupportScheduler())
    ctx_router = ContextAPIRouter(
        aggregator=aggregator,
        compression_router=comp_router,
        exposure_controller=ExposureController(),
        health_checker=ContextHealthChecker(),
        version_manager=ContextVersionManager(),
    )
    tool_governor = ToolContextGovernor(tools=SUPPORT_TOOLS)
    return ctx_router, tool_governor


async def main() -> None:
    ctx_router, tool_governor = setup_context_agent()
    agent = CRMSupportAgent(ctx_router, tool_governor)

    enquiries = [
        CustomerEnquiry(
            customer_id="customer:C001",
            session_id="support-session-20241201",
            message="我的账单里出现了一笔重复扣款，麻烦帮我查一下。",
            turn=1,
        ),
        CustomerEnquiry(
            customer_id="customer:C001",
            session_id="support-session-20241201",
            message="上次的退款申请处理了吗？编号是 T-2024-0892。",
            turn=2,
        ),
    ]

    for enquiry in enquiries:
        result = await agent.handle_enquiry(enquiry)
        print(f"\n✅ Agent ready to respond with {result['token_count']} tokens context")

    print("\n" + "="*60)
    print("📊 Summary")
    print("="*60)
    print(f"  Customer: C001 (Alice Wang)")
    print(f"  Context source: CRM LTM (4 memory items)")
    print(f"  Strategy: support_briefing (structured briefing)")
    print(f"  Tools exposed: {len([t for t in SUPPORT_TOOLS if 'support' in t.required_for_task_types])}/{len(SUPPORT_TOOLS)} total")


if __name__ == "__main__":
    asyncio.run(main())
