"""Strategy registry — maps strategy_id → CompressionStrategy instance."""

from __future__ import annotations

from typing import Any

from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.errors import StrategyNotFoundError
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class StrategyRegistry:
    """Singleton registry for compression strategies.

    Usage:
        registry = StrategyRegistry.instance()
        registry.register(MyStrategy())
        strategy = registry.get("my_strategy_id")
    """

    _instance: StrategyRegistry | None = None

    def __init__(self) -> None:
        self._strategies: dict[str, CompressionStrategy] = {}

    @classmethod
    def instance(cls) -> StrategyRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, strategy: CompressionStrategy) -> None:
        sid = strategy.strategy_id
        if sid in self._strategies:
            raise ValueError(f"Strategy '{sid}' already registered")
        self._strategies[sid] = strategy
        logger.info("strategy registered", strategy_id=sid)

    def get(self, strategy_id: str) -> CompressionStrategy:
        if strategy_id not in self._strategies:
            raise StrategyNotFoundError(strategy_id)
        return self._strategies[strategy_id]

    def list_ids(self) -> list[str]:
        return list(self._strategies.keys())

    def list(self) -> list[str]:
        """Backward-compatible alias expected by scheduler/tests."""
        return self.list_ids()

    def unregister(self, strategy_id: str) -> None:
        self._strategies.pop(strategy_id, None)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — used in tests only."""
        cls._instance = None


def ensure_default_strategies_registered(llm_adapter: Any | None = None) -> None:
    """Register built-in compression strategies if they are missing."""
    from context_agent.strategies.compaction_strategy import CompactionStrategy
    from context_agent.strategies.long_session_strategy import LongSessionCompressionStrategy
    from context_agent.strategies.qa_strategy import QACompressionStrategy
    from context_agent.strategies.realtime_strategy import RealtimeCompressionStrategy
    from context_agent.strategies.task_strategy import TaskCompressionStrategy

    registry = StrategyRegistry.instance()
    strategies = [
        QACompressionStrategy(llm_adapter=llm_adapter),
        TaskCompressionStrategy(llm_adapter=llm_adapter),
        LongSessionCompressionStrategy(llm_adapter=llm_adapter),
        RealtimeCompressionStrategy(),
        CompactionStrategy(llm_adapter=llm_adapter),
    ]
    for strategy in strategies:
        if strategy.strategy_id not in registry.list():
            registry.register(strategy)
            continue
        _refresh_strategy_llm_adapter(
            registry.get(strategy.strategy_id),
            llm_adapter=llm_adapter,
        )


def _refresh_strategy_llm_adapter(
    strategy: CompressionStrategy,
    llm_adapter: Any | None,
) -> None:
    """Attach/update llm_adapter on existing strategies that support it."""
    if llm_adapter is None or not hasattr(strategy, "_llm"):
        return
    current_llm = getattr(strategy, "_llm", None)
    if current_llm is llm_adapter:
        return
    setattr(strategy, "_llm", llm_adapter)
    logger.info("strategy llm adapter updated", strategy_id=strategy.strategy_id)
