"""Unit tests for data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from context_agent.models.context import (
    ContextItem,
    ContextOutput,
    ContextSnapshot,
    ContextView,
    MemoryType,
    OutputType,
)
from context_agent.models.metrics import AlertConfig, MetricRecord
from context_agent.models.policy import ExposurePolicy
from context_agent.models.ref import ContextRef, RefType
from context_agent.models.version import ContextVersionRecord


class TestContextItem:
    def test_default_id_generated(self):
        item = ContextItem(source_type="test")
        assert len(item.item_id) > 0

    def test_score_clamped_above_1(self):
        item = ContextItem(source_type="test", score=1.5)
        assert item.score == 1.0

    def test_score_clamped_below_0(self):
        item = ContextItem(source_type="test", score=-0.5)
        assert item.score == 0.0

    def test_memory_type_optional(self):
        item = ContextItem(source_type="tool_result")
        assert item.memory_type is None


class TestContextSnapshot:
    def test_default_fields(self):
        snap = ContextSnapshot(scope_id="s1")
        assert snap.items == []
        assert snap.total_tokens == 0

    def test_is_over_budget(self):
        snap = ContextSnapshot(scope_id="s1", total_tokens=5000, token_budget=4096)
        assert snap.is_over_budget is True

    def test_add_item(self):
        snap = ContextSnapshot(scope_id="s1")
        item = ContextItem(source_type="ltm")
        snap.add_item(item)
        assert len(snap.items) == 1
        assert snap.items[0].snapshot_id == snap.snapshot_id

    def test_query_field(self):
        snap = ContextSnapshot(scope_id="s1", query="What is X?")
        assert snap.query == "What is X?"


class TestContextOutput:
    def test_basic_fields(self):
        out = ContextOutput(
            output_type=OutputType.RAW,
            scope_id="s1",
            content="hello",
            token_count=10,
        )
        assert out.output_type == OutputType.RAW
        assert out.token_count == 10


class TestOutputType:
    def test_all_values(self):
        expected = {"snapshot", "summary", "search", "compressed_background", "compressed", "raw", "structured"}
        assert set(t.value for t in OutputType) == expected


class TestExposurePolicy:
    def test_allows_all_by_default(self):
        policy = ExposurePolicy(scope_id="s1")
        assert policy.allows_source_type("tool_result") is True
        assert policy.allows_memory_type(MemoryType.EPISODIC) is True
        assert policy.allows_tool("any_tool") is True

    def test_restricted_source_type(self):
        policy = ExposurePolicy(scope_id="s1", allowed_source_types=["ltm"])
        assert policy.allows_source_type("ltm") is True
        assert policy.allows_source_type("tool_result") is False

    def test_restricted_tool(self):
        policy = ExposurePolicy(scope_id="s1", allowed_tool_ids=["calc"])
        assert policy.allows_tool("calc") is True
        assert policy.allows_tool("web_search") is False


class TestContextRef:
    def test_basic_ref(self):
        ref = ContextRef(
            ref_type=RefType.VECTOR,
            scope_id="s1",
            locator="embedding_id_123",
        )
        assert ref.is_expired is False

    def test_expired_ref(self):
        import time
        ref = ContextRef(
            ref_type=RefType.MEMORY,
            scope_id="s1",
            locator="mem:abc",
            expires_at=time.time() - 1,
        )
        assert ref.is_expired is True


class TestAlertConfig:
    def test_defaults(self):
        cfg = AlertConfig()
        assert cfg.latency_p95_threshold_ms == 300.0
        assert cfg.cooldown_s == 300.0
        assert cfg.health_score_min == 0.5

    def test_token_budget_threshold(self):
        cfg = AlertConfig(token_budget_threshold=8192)
        assert cfg.token_budget_threshold == 8192


class TestMetricRecord:
    def test_basic(self):
        rec = MetricRecord(scope_id="s1", operation="test", latency_ms=42.0)
        assert rec.status == "ok"
        assert rec.token_count is None

    def test_with_status(self):
        rec = MetricRecord(scope_id="s1", operation="test", latency_ms=10.0, status="error")
        assert rec.status == "error"
