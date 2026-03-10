"""Example: tool context governance.

Demonstrates how ToolContextGovernor selects only relevant tools
for a given task, preventing context bloat from large toolsets.

Run:
    python examples/tool_governance.py
"""

from __future__ import annotations

import asyncio

from context_agent.core.retrieval.tool_governor import ToolContextGovernor, ToolDefinition
from context_agent.utils.logging import configure_logging, get_logger

configure_logging("INFO")
logger = get_logger(__name__)


# ── Define a realistic enterprise toolset ────────────────────────────────────

ALL_TOOLS = [
    # ── Data & Analytics
    ToolDefinition(
        tool_id="sql_query", name="SQL Query", category="data",
        description="Execute SQL queries against the data warehouse. Returns tabular results.",
        required_for_task_types=["analysis", "reporting"],
    ),
    ToolDefinition(
        tool_id="csv_export", name="CSV Export", category="data",
        description="Export query results to CSV format for download or processing.",
        required_for_task_types=["reporting"],
    ),
    ToolDefinition(
        tool_id="chart_generator", name="Chart Generator", category="data",
        description="Generate bar, line, or pie charts from numeric data.",
        required_for_task_types=["reporting", "presentation"],
    ),
    # ── Knowledge & Search
    ToolDefinition(
        tool_id="knowledge_search", name="Knowledge Search", category="search",
        description="Search the internal knowledge base for procedures, policies, and FAQs.",
        required_for_task_types=["qa", "support"],
    ),
    ToolDefinition(
        tool_id="web_search", name="Web Search", category="search",
        description="Search the public internet for recent news and external information.",
        required_for_task_types=["research", "qa"],
    ),
    ToolDefinition(
        tool_id="document_retrieval", name="Document Retrieval", category="search",
        description="Retrieve full text of a document by ID from the document store.",
        required_for_task_types=["qa", "analysis", "support"],
    ),
    # ── Communication
    ToolDefinition(
        tool_id="send_email", name="Send Email", category="communication",
        description="Send an email to one or more recipients via the corporate mail server.",
        required_for_task_types=["communication", "reporting"],
    ),
    ToolDefinition(
        tool_id="slack_message", name="Slack Message", category="communication",
        description="Post a message to a Slack channel or DM.",
        required_for_task_types=["communication"],
    ),
    ToolDefinition(
        tool_id="create_ticket", name="Create Ticket", category="communication",
        description="Create a Jira or ServiceNow ticket for issue tracking.",
        required_for_task_types=["support", "operations"],
    ),
    # ── Code & Dev
    ToolDefinition(
        tool_id="code_executor", name="Code Executor", category="dev",
        description="Execute Python code snippets in a sandboxed environment.",
        required_for_task_types=["analysis", "dev"],
    ),
    ToolDefinition(
        tool_id="git_operations", name="Git Operations", category="dev",
        description="Perform git operations: clone, diff, log, blame.",
        required_for_task_types=["dev", "review"],
    ),
    ToolDefinition(
        tool_id="test_runner", name="Test Runner", category="dev",
        description="Run automated test suites and return pass/fail results.",
        required_for_task_types=["dev", "qa"],
    ),
    # ── Calendar & Scheduling
    ToolDefinition(
        tool_id="calendar_check", name="Calendar Check", category="scheduling",
        description="Check availability and upcoming events for a team member.",
        required_for_task_types=["scheduling", "communication"],
    ),
    ToolDefinition(
        tool_id="meeting_scheduler", name="Meeting Scheduler", category="scheduling",
        description="Schedule a meeting and send calendar invites to participants.",
        required_for_task_types=["scheduling"],
    ),
    # ── Infrastructure
    ToolDefinition(
        tool_id="deployment_trigger", name="Deployment Trigger", category="ops",
        description="Trigger a CI/CD deployment pipeline for a specific service.",
        required_for_task_types=["operations", "dev"],
    ),
    ToolDefinition(
        tool_id="metrics_query", name="Metrics Query", category="ops",
        description="Query Prometheus or Datadog for system metrics and alerts.",
        required_for_task_types=["operations", "analysis"],
    ),
]


async def demo_task_type_filtering() -> None:
    """Show how task_type narrows the visible toolset."""
    governor = ToolContextGovernor(tools=ALL_TOOLS)

    print("=" * 60)
    print("🔧 Tool Context Governance Demo")
    print("=" * 60)
    print(f"\n📦 Total tools registered: {len(ALL_TOOLS)}")

    for task_type, description in [
        ("qa", "Customer Q&A Agent"),
        ("analysis", "Data Analysis Agent"),
        ("dev", "Code Review Agent"),
        ("reporting", "Report Generation Agent"),
    ]:
        selected = await governor.select_tools(
            scope_id="demo",
            task_description=f"Perform {task_type} task",
            task_type=task_type,
        )
        print(f"\n  [{task_type.upper()}] {description}:")
        print(f"   Tools exposed: {len(selected)}/{len(ALL_TOOLS)}")
        for tool in selected:
            print(f"   • {tool.name} ({tool.category})")


async def demo_context_items() -> None:
    """Show how selected tools become ContextItems for injection."""
    governor = ToolContextGovernor(tools=ALL_TOOLS[:5])
    items = await governor.get_tool_context_items(
        scope_id="demo",
        task_description="Answer customer support question",
        task_type="support",
    )
    print(f"\n📋 Tool ContextItems for injection ({len(items)}):")
    for item in items:
        print(f"   [{item.metadata.get('tool_id')}] {item.content[:60]}…")


async def main() -> None:
    await demo_task_type_filtering()
    await demo_context_items()
    print()


if __name__ == "__main__":
    asyncio.run(main())
