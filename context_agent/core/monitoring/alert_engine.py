"""Alert engine (UC016).

Evaluates MetricRecord batches against AlertConfig thresholds and fires
notifications via webhook or structured log when thresholds are breached.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from context_agent.models.metrics import AlertConfig, MetricRecord
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class AlertEngine:
    """Evaluates metrics against thresholds and dispatches notifications."""

    def __init__(
        self,
        config: AlertConfig | None = None,
        webhook_url: str = "",
    ) -> None:
        self._config = config or AlertConfig()
        self._webhook_url = webhook_url
        # {alert_key: last_fired_timestamp}  — per-condition cooldown tracking
        self._cooldowns: dict[str, float] = {}

    def update_config(self, config: AlertConfig) -> None:
        self._config = config

    def evaluate_batch(self, batch: list[MetricRecord]) -> None:
        """Evaluate a batch of MetricRecords; fire alerts for any breaches."""
        for record in batch:
            self._evaluate_one(record)

    def _evaluate_one(self, record: MetricRecord) -> None:
        cfg = self._config

        checks = [
            (
                record.latency_ms > cfg.latency_p95_threshold_ms,
                "latency_breach",
                lambda: f"latency {record.latency_ms:.1f}ms > threshold {cfg.latency_p95_threshold_ms}ms",
            ),
            (
                record.token_count is not None and record.token_count > cfg.token_budget_threshold,
                "token_budget_breach",
                lambda: f"tokens {record.token_count} > threshold {cfg.token_budget_threshold}",
            ),
            (
                record.status == "error",
                "error_status",
                lambda: f"operation '{record.operation}' returned error",
            ),
            (
                record.health_score is not None and record.health_score < cfg.health_score_min,
                "low_health_score",
                lambda: f"health score {record.health_score:.2f} < minimum {cfg.health_score_min}",
            ),
            (
                record.quality_score < cfg.quality_score_threshold,
                "quality_degradation",
                lambda: f"quality score {record.quality_score:.2f} < threshold {cfg.quality_score_threshold}",
            ),
        ]

        for triggered, alert_key, message_factory in checks:
            if triggered:
                full_key = f"{alert_key}:{record.scope_id}:{record.operation}"
                if self._in_cooldown(full_key):
                    continue
                self._fire(
                    alert_key=alert_key,
                    scope_id=record.scope_id,
                    operation=record.operation,
                    message=message_factory(),
                    record=record,
                )
                self._cooldowns[full_key] = time.monotonic()

    def _in_cooldown(self, key: str) -> bool:
        last = self._cooldowns.get(key)
        if last is None:
            return False
        return time.monotonic() - last < self._config.cooldown_s

    def _fire(
        self,
        alert_key: str,
        scope_id: str,
        operation: str,
        message: str,
        record: MetricRecord,
    ) -> None:
        logger.warning(
            "ALERT",
            alert_key=alert_key,
            scope_id=scope_id,
            operation=operation,
            message=message,
            latency_ms=record.latency_ms,
            status=record.status,
        )
        if self._webhook_url:
            asyncio.create_task(
                self._post_webhook(alert_key, scope_id, operation, message)
            )

    async def _post_webhook(
        self,
        alert_key: str,
        scope_id: str,
        operation: str,
        message: str,
    ) -> None:
        payload = {
            "alert_key": alert_key,
            "scope_id": scope_id,
            "operation": operation,
            "message": message,
            "timestamp": time.time(),
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self._webhook_url, json=payload)
        except Exception as exc:
            logger.warning("webhook delivery failed", url=self._webhook_url, error=str(exc))
