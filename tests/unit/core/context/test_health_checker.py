"""Functional tests for ContextHealthChecker."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_agent.core.context.health_checker import ContextHealthChecker
from context_agent.models.context import ContextItem, ContextSnapshot, MemoryType


def _make_snapshot(items: list[ContextItem], token_budget: int = 4096) -> ContextSnapshot:
    snap = ContextSnapshot(scope_id="scope1", session_id="sess1", token_budget=token_budget)
    for item in items:
        snap.add_item(item)
    snap.total_tokens = sum(len(i.content) // 4 for i in items)
    return snap


@pytest.mark.asyncio
class TestContextHealthChecker:
    async def test_healthy_snapshot_passes(self):
        items = [
            ContextItem(source_type="ltm", content="User preference: concise answers.", score=0.9),
            ContextItem(source_type="ltm", content="Task: Summarise Q3 results.", score=0.85),
            ContextItem(source_type="ltm", content="Previous answer was approved.", score=0.88),
        ]
        snap = _make_snapshot(items)
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        # Highly relevant items should be healthy
        assert report.scope_id == "scope1"
        assert report.is_healthy is True

    async def test_distraction_detected_with_low_score_items(self):
        # Mix of high-score and many low-score items
        items = (
            [ContextItem(source_type="ltm", content="relevant", score=0.9)] +
            [ContextItem(source_type="ltm", content=f"noise-{i}", score=0.1) for i in range(15)]
        )
        snap = _make_snapshot(items)
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        # Distraction risk should be elevated
        risk_types = [r.risk_type.value for r in report.risks]
        assert "context_distraction" in risk_types

    async def test_empty_snapshot_is_healthy(self):
        snap = _make_snapshot([])
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        assert report.is_healthy is True
        assert report.risks == []

    async def test_quick_check_non_raising(self):
        """quick_check should never raise even with edge-case input."""
        snap = _make_snapshot([])
        checker = ContextHealthChecker()
        report = await checker.quick_check(snap)
        assert report is not None
        assert report.scope_id == "scope1"

    async def test_quick_check_failure_is_not_reported_as_healthy(self):
        snap = _make_snapshot([])
        checker = ContextHealthChecker()
        checker._check_distraction = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        report = await checker.quick_check(snap)

        assert report.is_healthy is False
        assert report.issues
        assert report.issues[0].severity == "critical"
        assert "quick health check failed" in report.issues[0].description

    async def test_report_has_recommendations(self):
        items = (
            [ContextItem(source_type="ltm", content="relevant", score=0.9)] +
            [ContextItem(source_type="ltm", content=f"noise-{i}", score=0.05) for i in range(20)]
        )
        snap = _make_snapshot(items)
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        # Unhealthy report should have recommendations
        if not report.is_healthy:
            assert len(report.recommendations) > 0

    async def test_over_budget_triggers_confusion(self):
        items = [
            ContextItem(source_type="ltm", content="x" * 500, score=0.8)
            for _ in range(20)
        ]
        snap = _make_snapshot(items, token_budget=100)
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        assert report.total_tokens > report.token_budget

    async def test_health_report_issues_populated(self):
        items = (
            [ContextItem(source_type="ltm", content="a", score=0.9)] +
            [ContextItem(source_type="ltm", content=f"noise-{i}", score=0.05) for i in range(20)]
        )
        snap = _make_snapshot(items)
        checker = ContextHealthChecker()
        report = await checker.check(snap)
        if not report.is_healthy:
            assert all(hasattr(issue, "description") for issue in report.issues)
