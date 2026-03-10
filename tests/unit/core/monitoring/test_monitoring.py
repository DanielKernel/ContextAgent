"""Unit tests for monitoring collector and alert engine."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock

from context_agent.core.monitoring.alert_engine import AlertEngine
from context_agent.core.monitoring.collector import MonitoringCollector
from context_agent.models.metrics import AlertConfig, MetricRecord


def _make_record(**kwargs) -> MetricRecord:
    defaults = dict(scope_id="s1", operation="test", latency_ms=50.0)
    defaults.update(kwargs)
    return MetricRecord(**defaults)


@pytest.mark.asyncio
class TestMonitoringCollector:
    async def test_emit_and_flush(self):
        received: list[list[MetricRecord]] = []
        collector = MonitoringCollector(batch_size=2, flush_interval_s=0.05)
        collector.subscribe(lambda batch: received.append(batch))
        await collector.start()

        await collector.emit(_make_record())
        await collector.emit(_make_record())
        await collector.stop()

        total = sum(len(b) for b in received)
        assert total == 2

    async def test_flush_on_stop(self):
        received = []
        collector = MonitoringCollector(batch_size=100, flush_interval_s=60.0)
        collector.subscribe(lambda b: received.extend(b))
        await collector.start()
        await collector.emit(_make_record())
        await collector.stop()
        assert len(received) == 1

    def test_emit_sync_non_blocking(self):
        collector = MonitoringCollector()
        record = _make_record()
        collector.emit_sync(record)  # should not raise


class TestAlertEngine:
    def test_no_alert_within_threshold(self):
        engine = AlertEngine(AlertConfig(latency_p95_threshold_ms=300.0))
        fired = []
        engine._fire = lambda **kw: fired.append(kw)  # type: ignore
        engine.evaluate_batch([_make_record(latency_ms=100.0)])
        assert fired == []

    def test_latency_breach_fires_alert(self):
        config = AlertConfig(latency_p95_threshold_ms=100.0, cooldown_s=0.0)
        engine = AlertEngine(config)
        fired = []
        original_fire = engine._fire

        def capture(**kw):
            fired.append(kw)

        engine._fire = capture  # type: ignore
        engine.evaluate_batch([_make_record(latency_ms=500.0)])
        assert len(fired) == 1
        assert fired[0]["alert_key"] == "latency_breach"

    def test_cooldown_suppresses_repeated_alerts(self):
        config = AlertConfig(latency_p95_threshold_ms=100.0, cooldown_s=3600.0)
        engine = AlertEngine(config)
        fired = []
        engine._fire = lambda **kw: fired.append(kw)  # type: ignore

        engine.evaluate_batch([_make_record(latency_ms=500.0)])
        engine.evaluate_batch([_make_record(latency_ms=500.0)])
        assert len(fired) == 1  # second alert suppressed by cooldown

    def test_error_status_fires_alert(self):
        config = AlertConfig(cooldown_s=0.0)
        engine = AlertEngine(config)
        fired = []
        engine._fire = lambda **kw: fired.append(kw)  # type: ignore
        engine.evaluate_batch([_make_record(status="error")])
        assert any(f["alert_key"] == "error_status" for f in fired)

    def test_low_health_score_fires_alert(self):
        config = AlertConfig(health_score_min=0.5, cooldown_s=0.0)
        engine = AlertEngine(config)
        fired = []
        engine._fire = lambda **kw: fired.append(kw)  # type: ignore
        engine.evaluate_batch([_make_record(health_score=0.2)])
        assert any(f["alert_key"] == "low_health_score" for f in fired)
