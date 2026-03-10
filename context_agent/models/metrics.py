"""Monitoring and alerting data models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LatencyBreakdown(BaseModel):
    """Per-tier latency decomposition for a single recall operation."""

    hot_tier_ms: float = 0.0
    warm_tier_ms: float = 0.0
    cold_tier_ms: float = 0.0
    rerank_ms: float = 0.0
    exposure_control_ms: float = 0.0
    compression_ms: float = 0.0


class MetricRecord(BaseModel):
    """Telemetry record for a single ContextAgent operation."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope_id: str
    uc_id: str = ""  # e.g. "UC001", "UC002"
    operation: str  # e.g. "aggregate", "tiered_recall", "compress"
    strategy: str = ""  # compression / retrieval strategy used
    latency_ms: float
    status: str = "ok"  # ok | error | degraded
    token_count: int | None = None  # total tokens in this operation
    health_score: float | None = None  # context health score [0, 1]
    latency_breakdown: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    quality_score: float = 1.0   # composite recall quality [0, 1]
    token_input: int = 0
    token_output: int = 0
    degraded_count: int = 0      # number of sources that fell back
    rerank_skipped: bool = False
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AlertSeverity(str):
    """Alert severity levels."""

    P1 = "P1"  # critical – immediate response required
    P2 = "P2"  # high – response within 30 min
    P3 = "P3"  # medium – response within 2 h


class AlertConfig(BaseModel):
    """Alerting thresholds and notification configuration."""

    config_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope_id: str | None = None  # None = global config

    latency_p95_threshold_ms: float = 300.0
    latency_p99_threshold_ms: float = 800.0
    quality_score_threshold: float = 0.6
    degradation_rate_threshold: float = 0.2  # fraction of degraded sources
    error_rate_threshold: float = 0.01       # 1% error rate → P1
    token_budget_threshold: int = 4096       # alert when token_count exceeds this
    health_score_min: float = 0.5            # alert when health score drops below
    cooldown_s: float = 300.0               # seconds between repeated alerts for same condition

    # Notification channels: "log", "webhook", "mq"
    notification_channels: list[str] = Field(default_factory=lambda: ["log"])
    webhook_url: str | None = None

    updated_at: datetime = Field(default_factory=datetime.utcnow)
