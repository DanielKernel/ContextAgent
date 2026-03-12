"""Context health checker (UC003).

Detects the four canonical context failure modes:
  - Context poisoning   : incorrect/stale information contaminating context
  - Context distraction : too much irrelevant information reducing focus
  - Context confusion   : conflicting or ambiguous information
  - Context clash       : multiple context fragments with contradictory claims
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from context_agent.adapters.context_engine_adapter import ContextEnginePort
from context_agent.config.defaults import (
    HEALTH_CLASH_THRESHOLD,
    HEALTH_CONFUSION_THRESHOLD,
    HEALTH_DISTRACTION_THRESHOLD,
    HEALTH_POISONING_THRESHOLD,
)
from context_agent.models.context import ContextSnapshot
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class RiskType(str, Enum):
    POISONING = "context_poisoning"
    DISTRACTION = "context_distraction"
    CONFUSION = "context_confusion"
    CLASH = "context_clash"


@dataclass
class RiskIndicator:
    risk_type: RiskType
    score: float  # 0.0 = no risk, 1.0 = maximum risk
    affected_item_ids: list[str] = field(default_factory=list)
    details: str = ""


@dataclass
class HealthIssue:
    description: str
    severity: str = "warning"  # warning | critical


@dataclass
class HealthReport:
    scope_id: str
    is_healthy: bool
    risks: list[RiskIndicator] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    issues: list[HealthIssue] = field(default_factory=list)
    total_tokens: int = 0
    token_budget: int = 0

    @property
    def highest_risk_score(self) -> float:
        return max((r.score for r in self.risks), default=0.0)


class ContextHealthChecker:
    """Asynchronous health checker for context snapshots.

    Runs as a background task; does not block the main inference path.
    Uses openJiuwen MemUpdateChecker for conflict detection when available.
    """

    def __init__(
        self,
        context_engine: ContextEnginePort | None = None,
        mem_update_checker: Any | None = None,  # openjiuwen MemUpdateChecker
    ) -> None:
        self._ce = context_engine
        self._checker = mem_update_checker

    async def check(self, snapshot: ContextSnapshot) -> HealthReport:
        """Analyse a snapshot and return a HealthReport."""
        risks: list[RiskIndicator] = []

        async with asyncio.TaskGroup() as tg:
            t_dist = tg.create_task(self._check_distraction(snapshot))
            t_conf = tg.create_task(self._check_confusion(snapshot))
            t_clash = tg.create_task(self._check_clash(snapshot))

        risks.extend([t_dist.result(), t_conf.result(), t_clash.result()])

        is_healthy = all(r.score < _threshold(r.risk_type) for r in risks)
        recommendations = _build_recommendations(risks, snapshot)
        issues = [
            HealthIssue(
                description=f"{r.risk_type}: score={r.score:.2f}. {r.details}",
                severity="critical" if r.score >= 0.9 else "warning",
            )
            for r in risks
            if r.score >= _threshold(r.risk_type)
        ]

        report = HealthReport(
            scope_id=snapshot.scope_id,
            is_healthy=is_healthy,
            risks=[r for r in risks if r.score > 0],
            recommendations=recommendations,
            issues=issues,
            total_tokens=snapshot.total_tokens,
            token_budget=snapshot.token_budget,
        )
        if not is_healthy:
            logger.warning(
                "unhealthy context detected",
                scope_id=snapshot.scope_id,
                risks=[r.risk_type for r in risks if r.score >= _threshold(r.risk_type)],
            )
        return report

    async def quick_check(self, snapshot: ContextSnapshot) -> HealthReport:
        """Non-blocking abbreviated health check (skips clash detection)."""
        try:
            dist = await self._check_distraction(snapshot)
            conf = await self._check_confusion(snapshot)
            risks = [dist, conf]
            is_healthy = all(r.score < _threshold(r.risk_type) for r in risks)
            issues = [
                HealthIssue(
                    description=f"{r.risk_type}: score={r.score:.2f}. {r.details}",
                )
                for r in risks
                if r.score >= _threshold(r.risk_type)
            ]
            return HealthReport(
                scope_id=snapshot.scope_id,
                is_healthy=is_healthy,
                risks=[r for r in risks if r.score > 0],
                issues=issues,
                total_tokens=snapshot.total_tokens,
                token_budget=snapshot.token_budget,
            )
        except Exception as exc:
            logger.warning("quick_check failed", scope_id=snapshot.scope_id, error=str(exc))
            return HealthReport(
                scope_id=snapshot.scope_id,
                is_healthy=False,
                issues=[
                    HealthIssue(
                        description=f"quick health check failed: {exc}",
                        severity="critical",
                    )
                ],
                recommendations=[
                    "Investigate the health-check failure before trusting this quick-check result"
                ],
                total_tokens=snapshot.total_tokens,
                token_budget=snapshot.token_budget,
            )

    async def check_background(self, snapshot: ContextSnapshot) -> None:
        """Fire-and-forget health check; logs warnings but does not raise."""
        try:
            await self.check(snapshot)
        except Exception as exc:
            logger.warning("health check failed", scope_id=snapshot.scope_id, error=str(exc))

    # ── Risk detectors ────────────────────────────────────────────────────────

    async def _check_distraction(self, snapshot: ContextSnapshot) -> RiskIndicator:
        """High score when too many items have low relevance scores."""
        if not snapshot.items:
            return RiskIndicator(RiskType.DISTRACTION, 0.0)
        low_score_items = [i for i in snapshot.items if i.score < 0.4]
        score = len(low_score_items) / len(snapshot.items)
        return RiskIndicator(
            RiskType.DISTRACTION,
            score,
            affected_item_ids=[i.item_id for i in low_score_items],
            details=f"{len(low_score_items)}/{len(snapshot.items)} items have low relevance",
        )

    async def _check_confusion(self, snapshot: ContextSnapshot) -> RiskIndicator:
        """High score when multiple items have similar scores suggesting ambiguity."""
        if len(snapshot.items) < 5:
            return RiskIndicator(RiskType.CONFUSION, 0.0)
        scores = sorted([i.score for i in snapshot.items], reverse=True)
        if scores[2] >= 0.8:
            return RiskIndicator(RiskType.CONFUSION, 0.0)
        top3_spread = scores[0] - scores[2] if len(scores) >= 3 else 1.0
        # Low spread in top scores → many equally-ranked items → potential confusion
        score = max(0.0, 1.0 - top3_spread * 2)
        return RiskIndicator(RiskType.CONFUSION, score)

    async def _check_clash(self, snapshot: ContextSnapshot) -> RiskIndicator:
        """High score when conflicting items detected (via MemUpdateChecker or heuristic)."""
        if self._checker is not None:
            try:
                messages = [{"role": "user", "content": i.content} for i in snapshot.items]
                result = await self._checker.check(
                    messages=messages, user_id=snapshot.scope_id
                )
                conflicts = getattr(result, "conflicts", [])
                if conflicts:
                    return RiskIndicator(
                        RiskType.CLASH,
                        min(1.0, len(conflicts) / max(len(snapshot.items), 1)),
                        details=f"{len(conflicts)} conflicting memory entries detected",
                    )
            except Exception as exc:
                logger.warning(
                    "MemUpdateChecker clash check failed",
                    scope_id=snapshot.scope_id,
                    error=str(exc),
                )

        # Heuristic: check for items with identical source_type but contradictory sources
        if snapshot.degraded_sources:
            score = min(1.0, len(snapshot.degraded_sources) / 3)
            return RiskIndicator(RiskType.CLASH, score, details="degraded sources detected")
        return RiskIndicator(RiskType.CLASH, 0.0)


def _threshold(risk_type: RiskType) -> float:
    return {
        RiskType.POISONING: HEALTH_POISONING_THRESHOLD,
        RiskType.DISTRACTION: HEALTH_DISTRACTION_THRESHOLD,
        RiskType.CONFUSION: HEALTH_CONFUSION_THRESHOLD,
        RiskType.CLASH: HEALTH_CLASH_THRESHOLD,
    }[risk_type]


def _build_recommendations(risks: list[RiskIndicator], snapshot: ContextSnapshot) -> list[str]:
    recs = []
    for risk in risks:
        t = _threshold(risk.risk_type)
        if risk.score >= t:
            if risk.risk_type == RiskType.DISTRACTION:
                recs.append("Filter low-relevance items or raise the score threshold in ExposurePolicy")
            elif risk.risk_type == RiskType.CONFUSION:
                recs.append("Rerank results or increase diversity in retrieval to reduce ambiguity")
            elif risk.risk_type == RiskType.CLASH:
                recs.append("Run AsyncMemoryProcessor to resolve conflicts; consider routing UC003 for cleanup")
    if snapshot.is_over_budget:
        recs.append(f"Context exceeds token budget ({snapshot.total_tokens}/{snapshot.token_budget}); trigger UC009 compression")
    return recs
