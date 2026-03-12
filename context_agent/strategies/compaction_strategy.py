"""High-fidelity compaction strategy.

For long-running tasks approaching context window limits.
Preserves: architectural decisions, constraints, open questions, current progress.
Removes: resolved steps, duplicate reasoning, verbose tool outputs.
"""

from __future__ import annotations

import json
from typing import Any

from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType
from context_agent.strategies.base import CompressionStrategy
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

_COMPACTION_SYSTEM_PROMPT = """You are performing a high-fidelity context compaction for a
long-running agent task. Your goal is to produce a compact but complete summary that allows
the task to continue correctly.

MUST preserve (never drop):
- Architectural / design decisions and their rationale
- Non-negotiable constraints and requirements
- Open / unresolved questions
- Current task phase and next actions
- Key artifacts and their locations

SHOULD remove:
- Completed sub-steps with no future relevance
- Duplicate or near-duplicate messages
- Verbose raw tool outputs that have been processed
- Exploratory reasoning that led to dead ends

Return a JSON object with:
{
  "summary": "<concise prose summary>",
  "key_decisions": ["<decision 1>", ...],
  "constraints": ["<constraint 1>", ...],
  "open_questions": ["<question 1>", ...],
  "current_status": "<current phase and next action>",
  "compressed_messages": [{"role": "...", "content": "..."}]
}"""


class CompactionStrategy(CompressionStrategy):
    """High-fidelity compaction for long tasks near context window limits."""

    @property
    def strategy_id(self) -> str:
        return "compaction"

    def __init__(self, llm_adapter: Any | None = None) -> None:
        self._llm = llm_adapter

    async def compress(
        self,
        snapshot: ContextSnapshot,
        **kwargs: Any,
    ) -> ContextOutput:
        messages = self.snapshot_to_messages(snapshot)
        if not messages:
            return self.build_output(snapshot, [], output_type=OutputType.STRUCTURED)

        token_budget = snapshot.token_budget
        task_description = snapshot.query
        current_tokens = self.estimate_tokens(snapshot)
        if current_tokens <= token_budget:
            return self.build_output(snapshot, messages, output_type=OutputType.STRUCTURED)

        if self._llm is not None:
            compacted = await self._llm_compact(messages, token_budget, task_description)
            return self.build_output(snapshot, compacted, output_type=OutputType.STRUCTURED)

        return self.build_output(
            snapshot,
            self._structured_truncate(messages, token_budget),
            output_type=OutputType.STRUCTURED,
        )

    async def _llm_compact(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
        task_description: str,
    ) -> list[dict[str, Any]]:
        try:
            user_content = (
                f"Token budget: {token_budget}\n"
                f"Task: {task_description}\n"
                f"Messages to compact:\n{json.dumps(messages, ensure_ascii=False)}"
            )
            result_text = await self._llm.complete(
                system_prompt=_COMPACTION_SYSTEM_PROMPT,
                user_message=user_content,
                max_tokens=token_budget,
                temperature=0.1,
            )
            data = json.loads(result_text)
            compressed = data.get("compressed_messages", [])
            if not compressed:
                # Fallback: build from structured fields
                summary_parts = [f"## Task Summary\n{data.get('summary', '')}"]
                if data.get("key_decisions"):
                    summary_parts.append(
                        "## Key Decisions\n" + "\n".join(f"- {d}" for d in data["key_decisions"])
                    )
                if data.get("constraints"):
                    summary_parts.append(
                        "## Constraints\n" + "\n".join(f"- {c}" for c in data["constraints"])
                    )
                if data.get("open_questions"):
                    summary_parts.append(
                        "## Open Questions\n" + "\n".join(f"- {q}" for q in data["open_questions"])
                    )
                if data.get("current_status"):
                    summary_parts.append(f"## Current Status\n{data['current_status']}")
                return [{"role": "system", "content": "\n\n".join(summary_parts)}]
            return self.validate_messages(compressed, strategy_id=self.strategy_id)
        except Exception as exc:
            logger.warning("compaction LLM call failed, using structured truncate", error=str(exc))
            return self._structured_truncate(messages, token_budget)

    def _structured_truncate(
        self, messages: list[dict[str, Any]], token_budget: int
    ) -> list[dict[str, Any]]:
        """Keep system messages + last messages fitting within budget."""
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
