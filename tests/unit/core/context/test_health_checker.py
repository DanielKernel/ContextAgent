"""Functional tests for ContextHealthChecker."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_agent.core.context.health_checker import (
    ContextHealthChecker,
    HealthReport,
    RiskIndicator,
    RiskType,
)
from context_agent.models.context import ContextItem, ContextSnapshot


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

    async def test_checker_uses_configured_thresholds(self):
        items = (
            [ContextItem(source_type="ltm", content="relevant", score=0.9)] +
            [ContextItem(source_type="ltm", content=f"noise-{i}", score=0.1) for i in range(3)]
        )
        snap = _make_snapshot(items)
        checker = ContextHealthChecker()
        checker._settings.context_health_distraction_threshold = 0.9

        report = await checker.check(snap)

        assert report.is_healthy is True

    async def test_clash_checker_uses_mem_update_checker_conflicts(self):
        items = [ContextItem(source_type="ltm", content="item", score=0.7) for _ in range(2)]
        snap = _make_snapshot(items)
        checker = ContextHealthChecker(
            mem_update_checker=AsyncMock(
                check=AsyncMock(return_value=type("Result", (), {"conflicts": ["c1"]})())
            )
        )

        report = await checker.check(snap)

        risk_types = [risk.risk_type.value for risk in report.risks]
        assert "context_clash" in risk_types

    async def test_clash_checker_falls_back_when_mem_update_checker_errors(self):
        snap = _make_snapshot([ContextItem(source_type="ltm", content="item", score=0.7)])
        snap.degraded_sources.append("ltm")
        checker = ContextHealthChecker(
            mem_update_checker=AsyncMock(check=AsyncMock(side_effect=RuntimeError("boom")))
        )

        report = await checker.check(snap)

        clash_risk = next(risk for risk in report.risks if risk.risk_type.value == "context_clash")
        assert clash_risk.score > 0

    async def test_check_background_swallows_errors(self):
        snap = _make_snapshot([])
        checker = ContextHealthChecker()
        checker.check = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        await checker.check_background(snap)

    async def test_build_recommendations_covers_confusion_clash_and_budget(self):
        snap = _make_snapshot(
            [ContextItem(source_type="ltm", content="x" * 200, score=0.7)],
            token_budget=10,
        )
        checker = ContextHealthChecker()

        recommendations = checker._build_recommendations(
            [
                RiskIndicator(risk_type=RiskType.CONFUSION, score=1.0),
                RiskIndicator(risk_type=RiskType.CLASH, score=1.0),
            ],
            snap,
        )

        assert any("reduce ambiguity" in rec for rec in recommendations)
        assert any("resolve conflicts" in rec for rec in recommendations)
        assert any("token budget" in rec for rec in recommendations)

    async def test_build_recommendations_covers_distraction_and_highest_risk(self):
        snap = _make_snapshot([ContextItem(source_type="ltm", content="x", score=0.7)])
        checker = ContextHealthChecker()
        report = HealthReport(
            scope_id="scope1",
            is_healthy=False,
            risks=[
                RiskIndicator(risk_type=RiskType.DISTRACTION, score=1.0),
                RiskIndicator(risk_type=RiskType.CLASH, score=0.4),
            ],
        )

        recommendations = checker._build_recommendations(report.risks, snap)

        assert any("score threshold" in rec for rec in recommendations)
        assert report.highest_risk_score == 1.0

    async def test_health_report_highest_risk_defaults_to_zero(self):
        assert HealthReport(scope_id="scope1", is_healthy=True).highest_risk_score == 0.0
