"""Long session rolling summary strategy.

Wraps openJiuwen MessageSummaryOffloader for incremental rolling summarization.
openjiuwen path: openjiuwen.core.context_engine.processor.offloader.MessageSummaryOffloader
"""

from __future__ import annotations

import json
from typing import Any

from context_agent.models.context import ContextOutput, ContextSnapshot
from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

_SUMMARY_SYSTEM_PROMPT = """You are summarizing a long conversation for ongoing use.
Create a concise rolling summary that captures: key facts, decisions made, user preferences,
pending topics, and current context. The summary should allow the conversation to continue
naturally. Return a single summary string (not JSON)."""

_COMPRESS_SYSTEM_PROMPT = """Given a summary of earlier conversation and recent messages,
produce a compressed context. Keep the summary + the most recent messages that fit the budget.
Return a JSON array of message objects with 'role' and 'content' fields."""


class LongSessionCompressionStrategy(CompressionStrategy):
    """Rolling summary strategy for long multi-turn sessions."""

    @property
    def strategy_id(self) -> str:
        return "long_session"

    def __init__(
        self,
        message_summary_offloader: Any | None = None,
        llm_adapter: Any | None = None,
        summary_window: int = 20,  # summarize oldest N messages
    ) -> None:
        self._offloader = message_summary_offloader
        self._llm = llm_adapter
        self._summary_window = summary_window

    async def compress(
        self,
        snapshot: ContextSnapshot,
        **kwargs: Any,
    ) -> ContextOutput:
        messages = self.snapshot_to_messages(snapshot)
        if not messages:
            return self.build_output(snapshot, [])

        token_budget = snapshot.token_budget
        current_tokens = self.estimate_tokens(snapshot)
        if current_tokens <= token_budget:
            return self.build_output(snapshot, messages)

        # Try openJiuwen MessageSummaryOffloader
        if self._offloader is not None:
            try:
                result = await self._offloader.offload(
                    messages=messages,
                    token_budget=token_budget,
                    user_id=snapshot.scope_id,
                )
                if result:
                    compressed = result if isinstance(result, list) else messages
                    return self.build_output(snapshot, compressed)
            except Exception as exc:
                logger.warning("MessageSummaryOffloader failed", error=str(exc))

        # LLM-based rolling summary
        if self._llm is not None:
            compressed = await self._rolling_summary(messages, token_budget, snapshot.scope_id)
            return self.build_output(snapshot, compressed)

        return self.build_output(snapshot, self._simple_window(messages, token_budget))

    async def _rolling_summary(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        scope_id: str,
    ) -> list[dict[str, Any]]:
        try:
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]

            # Summarize the oldest chunk
            to_summarize = non_system[: self._summary_window]
            recent = non_system[self._summary_window :]

            summary_text = await self._llm.complete(
                system_prompt=_SUMMARY_SYSTEM_PROMPT,
                user_message=json.dumps(to_summarize),
                max_tokens=512,
                temperature=0.2,
            )
            summary_msg = {"role": "system", "content": f"[Conversation summary]\n{summary_text}"}

            # Compress summary + recent into budget
            candidate = system_msgs + [summary_msg] + recent
            if self.estimate_message_tokens(candidate) <= token_budget:
                return candidate

            # Still over budget: summarize again with LLM
            result_text = await self._llm.complete(
                system_prompt=_COMPRESS_SYSTEM_PROMPT,
                user_message=f"Token budget: {token_budget}\n{json.dumps(candidate)}",
                max_tokens=token_budget,
            )
            return json.loads(result_text)
        except Exception as exc:
            logger.warning("rolling summary failed", error=str(exc))
            return self._simple_window(messages, token_budget)

    def _simple_window(
        self, messages: list[dict[str, Any]], token_budget: int
    ) -> list[dict[str, Any]]:
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        chars_budget = token_budget * 4
        chars_used = sum(len(m.get("content", "")) for m in system)
        kept = []
        for msg in reversed(non_system):
            msg_len = len(msg.get("content", ""))
            if chars_used + msg_len <= chars_budget:
                kept.insert(0, msg)
                chars_used += msg_len
        return system + kept

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        if snapshot.total_tokens > 0:
            return snapshot.total_tokens
        return self.estimate_message_tokens(self.snapshot_to_messages(snapshot))
