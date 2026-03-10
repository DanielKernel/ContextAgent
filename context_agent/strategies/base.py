"""Compression strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CompressionStrategy(ABC):
    """Abstract interface for all context compression strategies.

    Each strategy encapsulates a single compression algorithm.
    Register implementations via StrategyRegistry at startup.
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique identifier used for registry lookup (e.g. 'qa', 'task')."""

    @abstractmethod
    async def compress(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        scope_id: str = "",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Compress messages to fit within token_budget.

        Args:
            messages: List of message dicts (role/content format).
            token_budget: Maximum tokens allowed in the output.
            scope_id: Scope identifier for logging / context.
            **kwargs: Strategy-specific parameters.

        Returns:
            Compressed list of messages.
        """

    @abstractmethod
    async def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate the total token count for a message list."""
