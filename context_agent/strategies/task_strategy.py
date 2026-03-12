"""Task execution compression strategy.

Wraps openJiuwen TaskMemoryService for task-oriented state preservation.
openjiuwen path: TaskMemoryService.summarize (ACE/ReasoningBank/ReME algorithms)
"""

from __future__ import annotations

import json
from typing import Any

from context_agent.models.context import ContextOutput, ContextSnapshot
from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are a context compression assistant for task execution.
Preserve: current task state, completed steps, pending actions, key decisions, constraints.
Remove: verbose tool outputs, duplicate reasoning, resolved questions.
Return a JSON array of message objects with 'role' and 'content' fields."""


class TaskCompressionStrategy(CompressionStrategy):
    """Compresses context by preserving task state and stripping process noise."""

    @property
    def strategy_id(self) -> str:
        return "task"

    def __init__(self, task_memory_service: Any | None = None, llm_adapter: Any | None = None) -> None:
        self._tms = task_memory_service
        self._llm = llm_adapter

    async def compress(
        self,
        snapshot: ContextSnapshot,
        **kwargs: Any,
    ) -> ContextOutput:
        messages = self.snapshot_to_messages(snapshot)
        if not messages:
            return self.build_output(snapshot, [])

        token_budget = snapshot.token_budget
        task_description = snapshot.query
        current_tokens = self.estimate_tokens(snapshot)
        if current_tokens <= token_budget:
            return self.build_output(snapshot, messages)

        # Try openJiuwen TaskMemoryService.summarize
        if self._tms is not None:
            try:
                summary = await self._tms.summarize(
                    messages=messages,
                    task_description=task_description,
                    user_id=snapshot.scope_id,
                )
                if summary:
                    return self.build_output(
                        snapshot,
                        [{"role": "system", "content": str(summary)}],
                    )
            except Exception as exc:
                logger.warning("TaskMemoryService.summarize failed", error=str(exc))

        # LLM fallback
        if self._llm is not None:
            try:
                user_content = (
                    f"Token budget: {token_budget}\n"
                    f"Task: {task_description}\n"
                    f"Messages:\n{json.dumps(messages)}"
                )
                result_text = await self._llm.complete(
                    system_prompt=_SYSTEM_PROMPT,
                    user_message=user_content,
                    max_tokens=token_budget,
                )
                return self.build_output(snapshot, json.loads(result_text))
            except Exception as exc:
                logger.warning("LLM task compression failed", error=str(exc))

        # Fallback: keep system + last few messages
        return self.build_output(snapshot, self._keep_recent(messages, token_budget))

    def _keep_recent(
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
