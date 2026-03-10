"""QA scenario compression strategy.

Wraps openJiuwen DialogueCompressor for high-relevance fragment selection.
openjiuwen path: openjiuwen.core.context_engine.processor.compressor.DialogueCompressor
"""

from __future__ import annotations

import json
from typing import Any

from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.errors import CompressionError
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are a context compression assistant for a QA system.
Given a conversation and a token budget, select the most relevant message fragments
that would help answer the user's question. Keep full messages when they are highly relevant;
summarize or drop messages that are tangential. Return a JSON array of message objects
with 'role' and 'content' fields."""


class QACompressionStrategy(CompressionStrategy):
    """Compresses context by retaining high-relevance fragments for QA tasks."""

    @property
    def strategy_id(self) -> str:
        return "qa"

    def __init__(self, dialogue_compressor: Any | None = None, llm_adapter: Any | None = None) -> None:
        # dialogue_compressor: openjiuwen DialogueCompressor (optional, used when available)
        # llm_adapter: LLMPort fallback
        self._compressor = dialogue_compressor
        self._llm = llm_adapter

    async def compress(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        scope_id: str = "",
        query: str = "",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        current_tokens = await self.estimate_tokens(messages)
        if current_tokens <= token_budget:
            return messages

        # Try openJiuwen DialogueCompressor first
        if self._compressor is not None:
            try:
                result = await self._compressor.compress(
                    messages=messages,
                    token_budget=token_budget,
                    query=query,
                )
                return result if isinstance(result, list) else messages
            except Exception as exc:
                logger.warning("DialogueCompressor failed, falling back to LLM", error=str(exc))

        # LLM fallback
        if self._llm is not None:
            return await self._llm_compress(messages, token_budget, query)

        # Last resort: truncate from oldest messages
        return self._truncate(messages, token_budget)

    async def _llm_compress(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        query: str,
    ) -> list[dict[str, Any]]:
        try:
            user_content = f"Token budget: {token_budget}\nQuery: {query}\nMessages:\n{json.dumps(messages)}"
            result_text = await self._llm.complete(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_content,
                max_tokens=token_budget,
            )
            return json.loads(result_text)
        except Exception as exc:
            logger.warning("LLM compression failed, using truncation", error=str(exc))
            return self._truncate(messages, token_budget)

    def _truncate(
        self, messages: list[dict[str, Any]], token_budget: int
    ) -> list[dict[str, Any]]:
        """Keep system message + most recent messages within budget."""
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        result = system[:]
        chars_budget = token_budget * 4  # rough estimate: 1 token ≈ 4 chars
        chars_used = sum(len(m.get("content", "")) for m in result)
        for msg in reversed(non_system):
            msg_len = len(msg.get("content", ""))
            if chars_used + msg_len <= chars_budget:
                result.insert(len(system), msg)
                chars_used += msg_len
            else:
                break
        return result

    async def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 4  # rough estimate
