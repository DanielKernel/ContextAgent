"""Example: basic context recall using the ContextAggregator.

Demonstrates the minimal setup to retrieve context from an in-memory
LTM stub without any openJiuwen installation required.

Run:
    python examples/basic_recall.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from context_agent.models.context import ContextItem, MemoryType
from context_agent.orchestration.context_aggregator import (
    AggregationRequest,
    ContextAggregator,
)
from context_agent.utils.logging import configure_logging, get_logger

configure_logging("INFO")
logger = get_logger(__name__)


# ── Stub LTM: returns pre-seeded items ────────────────────────────────────────

class StubLTM:
    """Simulates a long-term memory store with static data."""

    SEED_DATA: list[dict] = [
        {
            "source_type": "ltm",
            "content": "The project deadline is end of Q3 2025.",
            "memory_type": MemoryType.EPISODIC,
            "score": 0.92,
        },
        {
            "source_type": "ltm",
            "content": "User prefers concise bullet-point summaries.",
            "memory_type": MemoryType.PROCEDURAL,
            "score": 0.88,
        },
        {
            "source_type": "ltm",
            "content": "Integration testing is handled by the QA team.",
            "memory_type": MemoryType.SEMANTIC,
            "score": 0.75,
        },
    ]

    async def search(self, scope_id: str, query: str, top_k: int = 10) -> list[ContextItem]:
        logger.info("StubLTM.search", scope_id=scope_id, query=query[:50])
        return [ContextItem(**d) for d in self.SEED_DATA[:top_k]]


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    ltm = StubLTM()
    aggregator = ContextAggregator(ltm=ltm)

    request = AggregationRequest(
        scope_id="demo-scope",
        session_id="session-001",
        query="What is the project deadline?",
        token_budget=1024,
        top_k=5,
    )

    snapshot = await aggregator.aggregate(request)

    print(f"\n📋 Context Snapshot for: '{request.query}'")
    print(f"   Scope: {snapshot.scope_id} | Session: {snapshot.session_id}")
    print(f"   Items: {len(snapshot.items)} | Tokens: {snapshot.total_tokens}\n")

    for i, item in enumerate(snapshot.items, 1):
        print(f"  [{i}] score={item.score:.2f} source={item.source_type}")
        print(f"      {item.content}\n")


if __name__ == "__main__":
    asyncio.run(main())
