"""Tool context governor (UC011).

Controls which tools are surfaced to the model based on task type and context.
For large toolsets, applies RAG-based selection; for small toolsets, returns all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from context_agent.adapters.retriever_adapter import RetrieverPort
from context_agent.config.defaults import TOOL_RAG_THRESHOLD, TOOL_TOP_K
from context_agent.models.context import ContextItem
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolDefinition:
    """Lightweight description of a callable tool."""

    tool_id: str
    name: str
    description: str
    category: str = ""
    required_for_task_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_context_item(self) -> ContextItem:
        return ContextItem(
            source_type="tool_definition",
            tier="hot",
            score=1.0,
            content=f"[{self.tool_id}] {self.name}: {self.description}",
            metadata={"tool_id": self.tool_id, "category": self.category},
        )


class ToolContextGovernor:
    """Governs which tools are injected into the model context window.

    Strategy:
      - ≤ TOOL_RAG_THRESHOLD tools → return all (pass-through)
      - >  TOOL_RAG_THRESHOLD tools → RAG-select top-k most relevant tools
    """

    def __init__(
        self,
        retriever: RetrieverPort | None = None,
        tools: list[ToolDefinition] | None = None,
    ) -> None:
        self._retriever = retriever
        self._tools: dict[str, ToolDefinition] = {
            t.tool_id: t for t in (tools or [])
        }

    def register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.tool_id] = tool

    def unregister_tool(self, tool_id: str) -> None:
        self._tools.pop(tool_id, None)

    async def select_tools(
        self,
        scope_id: str,
        task_description: str,
        task_type: str = "",
        top_k: int = TOOL_TOP_K,
    ) -> list[ToolDefinition]:
        """Return the most relevant tools for the given task."""
        candidate_tools = self._filter_by_task_type(task_type)

        if len(candidate_tools) <= TOOL_RAG_THRESHOLD:
            return candidate_tools

        # Use RAG selection for large toolsets
        if self._retriever is not None:
            selected = await self._rag_select(
                scope_id, task_description, candidate_tools, top_k
            )
            return selected

        # Fallback: return first top_k
        return candidate_tools[:top_k]

    async def get_tool_context_items(
        self,
        scope_id: str,
        task_description: str,
        task_type: str = "",
        top_k: int = TOOL_TOP_K,
    ) -> list[ContextItem]:
        """Return selected tools as ContextItems ready for injection."""
        tools = await self.select_tools(scope_id, task_description, task_type, top_k)
        return [t.to_context_item() for t in tools]

    def _filter_by_task_type(self, task_type: str) -> list[ToolDefinition]:
        if not task_type:
            return list(self._tools.values())
        result = []
        for tool in self._tools.values():
            if (
                not tool.required_for_task_types
                or task_type in tool.required_for_task_types
            ):
                result.append(tool)
        return result

    async def _rag_select(
        self,
        scope_id: str,
        task_description: str,
        candidate_tools: list[ToolDefinition],
        top_k: int,
    ) -> list[ToolDefinition]:
        """Use vector search on tool descriptions to select most relevant tools."""
        # Build a synthetic query combining task description and tool names
        combined_query = task_description + " " + " ".join(
            t.name for t in candidate_tools
        )
        items = await self._retriever.agentic_search(
            scope_id, combined_query, task_description, top_k
        )
        selected_ids = {
            item.metadata.get("tool_id")
            for item in items
            if item.metadata.get("tool_id")
        }
        # Return matched tools first, then fill up to top_k if needed
        matched = [t for t in candidate_tools if t.tool_id in selected_ids]
        if len(matched) < top_k:
            remainder = [t for t in candidate_tools if t.tool_id not in selected_ids]
            matched.extend(remainder[: top_k - len(matched)])
        return matched[:top_k]
