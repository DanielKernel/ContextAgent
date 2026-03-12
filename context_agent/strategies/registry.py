"""Strategy registry — maps strategy_id → CompressionStrategy instance."""

from __future__ import annotations

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


def ensure_default_strategies_registered() -> None:
    """Register built-in compression strategies if they are missing."""
    from context_agent.strategies.compaction_strategy import CompactionStrategy
    from context_agent.strategies.long_session_strategy import LongSessionCompressionStrategy
    from context_agent.strategies.qa_strategy import QACompressionStrategy
    from context_agent.strategies.realtime_strategy import RealtimeCompressionStrategy
    from context_agent.strategies.task_strategy import TaskCompressionStrategy

    registry = StrategyRegistry.instance()
    strategies = [
        QACompressionStrategy(),
        TaskCompressionStrategy(),
        LongSessionCompressionStrategy(),
        RealtimeCompressionStrategy(),
        CompactionStrategy(),
    ]
    for strategy in strategies:
        try:
            registry.register(strategy)
        except ValueError:
            continue
