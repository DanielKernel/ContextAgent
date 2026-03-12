"""Compression strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType


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
        snapshot: ContextSnapshot,
        **kwargs: Any,
    ) -> ContextOutput:
        """Compress a snapshot into a context output that fits its token budget.

        Args:
            snapshot: Aggregated context snapshot to compress.
            **kwargs: Strategy-specific parameters.

        Returns:
            Compressed output ready for injection.
        """

    @abstractmethod
    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        """Estimate the total token count for a snapshot."""

    @staticmethod
    def snapshot_to_messages(snapshot: ContextSnapshot) -> list[dict[str, Any]]:
        """Convert a snapshot into message-like dicts for strategy internals."""
        messages: list[dict[str, Any]] = []
        for item in snapshot.items:
            role = str(item.metadata.get("role", item.source_type)).strip() or "user"
            content = str(item.content)
            prefix = f"[{role}] "
            if content.startswith(prefix):
                content = content[len(prefix):]
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "metadata": dict(item.metadata),
                }
            )
        return messages

    @staticmethod
    def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
        """Rough token estimate for message-like dicts."""
        return sum(len(str(message.get("content", ""))) for message in messages) // 4

    @staticmethod
    def render_messages(messages: list[dict[str, Any]]) -> str:
        """Render message-like dicts into the text content returned to callers."""
        rendered: list[str] = []
        for message in messages:
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            role = str(message.get("role", "")).strip()
            rendered.append(f"[{role}] {content}" if role else content)
        return "\n\n".join(rendered)

    @classmethod
    def build_output(
        cls,
        snapshot: ContextSnapshot,
        messages: list[dict[str, Any]],
        *,
        output_type: OutputType = OutputType.COMPRESSED,
        metadata: dict[str, Any] | None = None,
    ) -> ContextOutput:
        """Build a ContextOutput from strategy-produced messages."""
        content = cls.render_messages(messages)
        return ContextOutput(
            output_type=output_type,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            user_id=snapshot.user_id,
            content=content,
            token_count=max(len(content) // 4, 0),
            metadata=metadata or {},
        )
