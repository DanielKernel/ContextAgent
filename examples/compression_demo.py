"""Example: context compression strategies.

Demonstrates how to use the compression strategy registry and router
to compress a large context snapshot using different strategies.

Run:
    python examples/compression_demo.py
"""

from __future__ import annotations

import asyncio

from context_agent.models.context import ContextItem, ContextOutput, ContextSnapshot, MemoryType, OutputType
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySchedule,
    StrategySelectionContext,
)
from context_agent.strategies.base import CompressionStrategy
from context_agent.strategies.registry import StrategyRegistry
from context_agent.utils.logging import configure_logging, get_logger

configure_logging("INFO")
logger = get_logger(__name__)


# ── Custom strategy: keyword extraction ──────────────────────────────────────

class KeywordExtractionStrategy(CompressionStrategy):
    """Simple demo strategy: extract first sentence from each item."""

    @property
    def strategy_id(self) -> str:
        return "keyword_extract"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        lines = []
        for item in snapshot.items:
            # Take first sentence only
            first_sentence = item.content.split("。")[0].split(".")[0].strip()
            if first_sentence:
                lines.append(f"[{item.source_type}] {first_sentence}")

        compressed = "\n".join(lines)
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=compressed,
            token_count=len(compressed) // 4,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return snapshot.total_tokens // 3  # estimates ~33% compression


# ── Build sample snapshot ─────────────────────────────────────────────────────

def build_large_snapshot() -> ContextSnapshot:
    snap = ContextSnapshot(
        scope_id="demo-scope",
        session_id="session-001",
        query="What are the latest system decisions?",
    )
    conversations = [
        ("ltm", MemoryType.EPISODIC,
         "On Nov 12, the team decided to adopt a microservices architecture for the payment module. "
         "This was driven by scalability concerns raised during load testing."),
        ("ltm", MemoryType.PROCEDURAL,
         "API responses must follow RFC 7807 Problem Details format. "
         "All error codes are documented in the error-catalog repository."),
        ("ltm", MemoryType.SEMANTIC,
         "The main database is PostgreSQL 16. Read replicas are deployed in us-east-2. "
         "Connection pooling is handled by PgBouncer with max_connections=200."),
        ("ltm", MemoryType.VARIABLE,
         "Current sprint goal: complete the context agent Phase 1 by Nov 30. "
         "Remaining tasks: integration tests, documentation, and demo preparation."),
        ("ltm", MemoryType.EPISODIC,
         "User feedback from Nov 8 demo: response times are acceptable but UI needs improvement. "
         "Priority items: dark mode, better error messages, keyboard shortcuts."),
    ]
    for source, mem_type, content in conversations:
        snap.add_item(ContextItem(
            source_type=source,
            memory_type=mem_type,
            content=content,
            score=0.85,
        ))
    snap.total_tokens = sum(len(i.content) // 4 for i in snap.items)
    return snap


# ── Main ──────────────────────────────────────────────────────────────────────

async def demo_builtin_registry() -> None:
    """Show all registered strategies."""
    registry = StrategyRegistry.instance()
    print("📚 Registered strategies:")
    for sid in registry.list():
        print(f"   • {sid}")
    print()


async def demo_custom_strategy(snapshot: ContextSnapshot) -> None:
    """Register and apply a custom strategy."""
    registry = StrategyRegistry.instance()
    if "keyword_extract" not in registry.list():
        registry.register(KeywordExtractionStrategy())

    strategy = registry.get("keyword_extract")
    print(f"🔧 Applying custom strategy: {strategy.strategy_id}")
    print(f"   Input tokens (estimate): {strategy.estimate_tokens(snapshot)}")

    output = await strategy.compress(snapshot)
    print(f"   Output tokens: {output.token_count}")
    print(f"   Compression ratio: {output.token_count / max(snapshot.total_tokens, 1):.0%}\n")
    print("📝 Compressed output:")
    print(output.content)
    print()


async def demo_router(snapshot: ContextSnapshot) -> None:
    """Use the router to auto-select strategy based on utilisation."""
    registry = StrategyRegistry.instance()
    if "keyword_extract" not in registry.list():
        registry.register(KeywordExtractionStrategy())

    # Fixed scheduler for demo
    class _FixedScheduler(HybridStrategyScheduler):
        def schedule(self, ctx: StrategySelectionContext) -> StrategySchedule:
            return StrategySchedule(strategy_ids=["keyword_extract"])

    router = CompressionStrategyRouter(scheduler=_FixedScheduler())
    ctx = StrategySelectionContext(
        scope_id="demo-scope",
        task_type="qa",
        token_used=snapshot.total_tokens,
        token_budget=4096,
    )
    output = await router.route_and_compress(snapshot, ctx)
    print(f"🚀 Router output ({output.output_type}):")
    print(f"   Tokens: {output.token_count}")
    print()


async def main() -> None:
    snapshot = build_large_snapshot()
    print(f"📋 Original snapshot: {len(snapshot.items)} items, {snapshot.total_tokens} tokens\n")

    await demo_builtin_registry()
    await demo_custom_strategy(snapshot)
    await demo_router(snapshot)


if __name__ == "__main__":
    asyncio.run(main())
