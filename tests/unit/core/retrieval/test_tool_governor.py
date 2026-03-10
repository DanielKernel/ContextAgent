"""Functional tests for ToolContextGovernor."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from context_agent.core.retrieval.tool_governor import ToolContextGovernor, ToolDefinition
from context_agent.config.defaults import TOOL_RAG_THRESHOLD


def _make_tools(n: int, category: str = "general") -> list[ToolDefinition]:
    return [
        ToolDefinition(
            tool_id=f"tool_{i}",
            name=f"Tool {i}",
            description=f"This tool does thing number {i}",
            category=category,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
class TestToolContextGovernor:
    async def test_small_toolset_returns_all(self):
        """Toolsets ≤ threshold are returned in full without RAG."""
        governor = ToolContextGovernor(tools=_make_tools(5))
        selected = await governor.select_tools("scope1", "execute task", top_k=10)
        assert len(selected) == 5

    async def test_large_toolset_triggers_rag(self):
        """Toolsets > threshold trigger RAG-based selection."""
        items_returned = [
            __import__("context_agent.models.context", fromlist=["ContextItem"]).ContextItem(
                source_type="tool_definition",
                content="Tool 0: This tool does thing number 0",
                metadata={"tool_id": "tool_0"},
            )
        ]
        retriever = AsyncMock()
        retriever.agentic_search = AsyncMock(return_value=items_returned)

        tools = _make_tools(TOOL_RAG_THRESHOLD + 5)
        governor = ToolContextGovernor(retriever=retriever, tools=tools)
        selected = await governor.select_tools("scope1", "test task", top_k=3)
        retriever.agentic_search.assert_awaited()
        assert len(selected) <= 3

    async def test_task_type_filter(self):
        tools = [
            ToolDefinition(tool_id="search", name="Search", description="web search",
                           required_for_task_types=["qa"]),
            ToolDefinition(tool_id="calc", name="Calc", description="calculator",
                           required_for_task_types=["math"]),
            ToolDefinition(tool_id="general", name="General", description="general purpose"),
        ]
        governor = ToolContextGovernor(tools=tools)
        selected = await governor.select_tools("scope1", "answer question", task_type="qa")
        ids = {t.tool_id for t in selected}
        assert "search" in ids
        assert "general" in ids
        assert "calc" not in ids

    async def test_register_and_unregister(self):
        governor = ToolContextGovernor()
        tool = ToolDefinition(tool_id="temp_tool", name="Temp", description="temporary")
        governor.register_tool(tool)
        assert "temp_tool" in {t.tool_id for t in governor._tools.values()}

        governor.unregister_tool("temp_tool")
        assert "temp_tool" not in {t.tool_id for t in governor._tools.values()}

    async def test_context_items_format(self):
        tools = _make_tools(3)
        governor = ToolContextGovernor(tools=tools)
        items = await governor.get_tool_context_items("scope1", "test task")
        assert len(items) == 3
        for item in items:
            assert item.source_type == "tool_definition"
            assert item.metadata.get("tool_id", "").startswith("tool_")

    async def test_empty_toolset_returns_empty(self):
        governor = ToolContextGovernor()
        selected = await governor.select_tools("scope1", "anything")
        assert selected == []

    async def test_no_task_type_returns_all_tools(self):
        tools = _make_tools(5)
        governor = ToolContextGovernor(tools=tools)
        selected = await governor.select_tools("scope1", "generic task", task_type="")
        assert len(selected) == 5
