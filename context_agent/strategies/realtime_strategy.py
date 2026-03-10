"""Realtime low-cost compression strategy.

Wraps openJiuwen CurrentRoundCompressor for fast, low-overhead compression.
openjiuwen path: openjiuwen.core.context_engine.processor.compressor.CurrentRoundCompressor
"""

from __future__ import annotations

from typing import Any

from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class RealtimeCompressionStrategy(CompressionStrategy):
    """Fast heuristic compression for high-throughput / low-latency scenarios.

    No LLM calls: uses sliding-window truncation and deduplication only.
    P95 compression latency target: < 5ms.
    """

    @property
    def strategy_id(self) -> str:
        return "realtime"

    def __init__(
        self,
        current_round_compressor: Any | None = None,
        keep_last_n: int = 10,
    ) -> None:
        self._compressor = current_round_compressor
        self._keep_last_n = keep_last_n

    async def compress(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        scope_id: str = "",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        current_tokens = await self.estimate_tokens(messages)
        if current_tokens <= token_budget:
            return messages

        # Try openJiuwen CurrentRoundCompressor (fast, no LLM)
        if self._compressor is not None:
            try:
                result = await self._compressor.compress(
                    messages=messages,
                    token_budget=token_budget,
                )
                if result and isinstance(result, list):
                    return result
            except Exception as exc:
                logger.warning("CurrentRoundCompressor failed", error=str(exc))

        return self._fast_truncate(messages, token_budget)

    def _fast_truncate(
        self, messages: list[dict[str, Any]], token_budget: int
    ) -> list[dict[str, Any]]:
        """Keep system message + last N non-system messages within budget."""
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        recent = non_system[-self._keep_last_n :]
        chars_budget = token_budget * 4
        chars_used = sum(len(m.get("content", "")) for m in system)
        kept = []
        for msg in reversed(recent):
            msg_len = len(msg.get("content", ""))
            if chars_used + msg_len <= chars_budget:
                kept.insert(0, msg)
                chars_used += msg_len
            else:
                break
        return system + kept

    async def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return sum(len(m.get("content", "")) for m in messages) // 4
