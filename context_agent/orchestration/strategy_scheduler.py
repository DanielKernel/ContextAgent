"""Hybrid strategy scheduler (UC005).

Selects the optimal combination of context enrichment strategies based on:
  - Task type classification
  - Current token budget utilisation
  - Agent role
  - Session history signals
"""

from __future__ import annotations

from dataclasses import dataclass, field

from context_agent.config.settings import get_settings
from context_agent.strategies.registry import (
    StrategyRegistry,
    ensure_default_strategies_registered,
)
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class StrategySelectionContext:
    """Runtime context used to choose strategies."""

    scope_id: str
    task_type: str = ""          # e.g. "qa", "task", "long_session", "realtime"
    agent_role: str = ""         # e.g. "planner", "executor", "reviewer"
    token_used: int = 0
    token_budget: int = 4096
    turn_count: int = 0
    has_multimodal: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def utilisation(self) -> float:
        if self.token_budget == 0:
            return 0.0
        return self.token_used / self.token_budget


@dataclass
class StrategySchedule:
    """Output of the scheduler: an ordered list of strategy IDs to apply."""

    strategy_ids: list[str]
    enable_hybrid_retrieval: bool = True
    enable_graph_retrieval: bool = False
    enable_ltm: bool = True
    rerank: bool = True
    notes: list[str] = field(default_factory=list)


class HybridStrategyScheduler:
    """Selects context enrichment strategies based on task context."""

    # Task-type → preferred strategy IDs (in priority order)
    TASK_TYPE_MAP: dict[str, list[str]] = {
        "qa": ["qa"],
        "task": ["task"],
        "long_session": ["long_session"],
        "realtime": ["realtime"],
        "compaction": ["compaction"],
    }

    def schedule(self, ctx: StrategySelectionContext) -> StrategySchedule:
        """Return a StrategySchedule for the given context."""
        settings = get_settings()
        ensure_default_strategies_registered()
        registry = StrategyRegistry.instance()
        available = set(registry.list())

        strategy_ids: list[str] = []
        notes: list[str] = []

        # 1. Task-type driven strategy selection
        preferred = self.TASK_TYPE_MAP.get(ctx.task_type, [])
        for sid in preferred:
            if sid in available:
                strategy_ids.append(sid)
            else:
                notes.append(f"Strategy '{sid}' not registered; skipping.")

        # 2. Fallback: auto-select based on signals
        if not strategy_ids:
            if ctx.turn_count > 20:
                strategy_ids = ["long_session"]
                notes.append("Auto-selected long_session (turn_count>20)")
            elif ctx.utilisation > settings.compaction_trigger_ratio:
                strategy_ids = ["compaction"]
                notes.append(
                    "Auto-selected compaction "
                    f"(utilisation>{settings.compaction_trigger_ratio:.0%})"
                )
            elif ctx.task_type == "":
                strategy_ids = ["qa"]
                notes.append("Auto-selected qa (default fallback)")

        # 3. Realtime override for very low budget
        if ctx.utilisation > 0.95 and "realtime" in available and "realtime" not in strategy_ids:
            strategy_ids.insert(0, "realtime")
            notes.append("Prepended realtime (utilisation>95%)")

        # 4. Retrieval config
        enable_graph = ctx.task_type in ("task", "compaction") or ctx.turn_count > 10
        enable_ltm = ctx.agent_role != "reviewer"  # reviewers don't need LTM

        logger.debug(
            "strategy scheduled",
            scope_id=ctx.scope_id,
            strategies=strategy_ids,
            utilisation=f"{ctx.utilisation:.0%}",
        )

        return StrategySchedule(
            strategy_ids=strategy_ids,
            enable_hybrid_retrieval=True,
            enable_graph_retrieval=enable_graph,
            enable_ltm=enable_ltm,
            rerank=ctx.utilisation < 0.9,  # skip rerank when very tight
            notes=notes,
        )
