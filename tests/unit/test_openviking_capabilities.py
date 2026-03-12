"""Unit tests for OpenViking-borrowed capabilities.

Covers:
  - Hotness Score (compute_hotness, hotness_blend)
  - ContextLevel / MemoryCategory model fields
  - ContextAggregator category_filter and max_level
  - WorkingMemoryManager.mark_used
  - TieredMemoryRouter.record_usage
  - ToolContextGovernor.record_tool_result + success-rate sorting
  - ContextAPIRouter.mark_used / record_tool_result façade
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_agent.core.memory.hotness import (
    HOTNESS_ALPHA,
    compute_hotness,
    hotness_blend,
)
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.core.retrieval.tool_governor import ToolContextGovernor, ToolDefinition
from context_agent.models.context import (
    ContextItem,
    ContextLevel,
    MemoryCategory,
    MemoryType,
)
from context_agent.models.note import NoteType, WorkingNote
from context_agent.orchestration.context_aggregator import (
    AggregationRequest,
    ContextAggregator,
)


# ── Hotness Score ──────────────────────────────────────────────────────────────

class TestComputeHotness:
    def test_never_used_fresh_is_neutral(self):
        """active_count=0, age=0 → sigmoid(0) × 1.0 = 0.5"""
        h = compute_hotness(0, datetime.now(tz=timezone.utc))
        assert abs(h - 0.5) < 0.01

    def test_frequently_used_fresh_is_hot(self):
        """High active_count + age=0 → close to 1.0"""
        h = compute_hotness(100, datetime.now(tz=timezone.utc))
        assert h > 0.95

    def test_half_life_decay(self):
        """active_count=100, age=7 days → halved by half-life"""
        fresh = compute_hotness(100, datetime.now(tz=timezone.utc))
        old = compute_hotness(100, datetime.now(tz=timezone.utc) - timedelta(days=7))
        assert abs(old - fresh * 0.5) < 0.05

    def test_two_half_lives(self):
        """14-day-old item should decay to ~25% of fresh frequency score."""
        fresh = compute_hotness(10, datetime.now(tz=timezone.utc))
        stale = compute_hotness(10, datetime.now(tz=timezone.utc) - timedelta(days=14))
        assert abs(stale / fresh - 0.25) < 0.05

    def test_negative_active_count_clamps(self):
        """negative active_count is treated as 0 — no error, no negative hotness"""
        h = compute_hotness(-5, datetime.now(tz=timezone.utc))
        assert 0.0 <= h <= 1.0

    def test_none_updated_at_uses_now(self):
        """Missing updated_at should not raise and use age=0 implicitly."""
        h = compute_hotness(5, None)
        assert 0.0 <= h <= 1.0

    def test_none_active_count_clamps_to_zero(self):
        h = compute_hotness(None, datetime.now(tz=timezone.utc))
        assert 0.0 <= h <= 1.0

    def test_tz_naive_updated_at_handled(self):
        """tz-naive updated_at should be treated as UTC without raising."""
        naive_old = datetime.utcnow() - timedelta(days=3)
        h = compute_hotness(5, naive_old)
        assert 0.0 <= h <= 1.0

    def test_non_positive_half_life_rejected(self):
        with pytest.raises(ValueError, match="half_life_days"):
            compute_hotness(5, datetime.now(tz=timezone.utc), half_life_days=0)


class TestHotnessBlend:
    def test_blend_formula(self):
        result = hotness_blend(0.8, 0.4, alpha=0.2)
        expected = 0.8 * 0.8 + 0.2 * 0.4
        assert abs(result - expected) < 1e-9

    def test_alpha_zero_returns_semantic_only(self):
        assert hotness_blend(0.7, 0.9, alpha=0.0) == pytest.approx(0.7)

    def test_alpha_one_returns_hotness_only(self):
        assert hotness_blend(0.7, 0.9, alpha=1.0) == pytest.approx(0.9)

    def test_alpha_clamped(self):
        """alpha > 1 or < 0 should be clamped, not raise."""
        h = hotness_blend(0.5, 0.5, alpha=5.0)
        assert 0.0 <= h <= 1.0


# ── Model fields ───────────────────────────────────────────────────────────────

class TestContextItemNewFields:
    def test_default_level_is_detail(self):
        item = ContextItem(source_type="test", content="x")
        assert item.level == ContextLevel.DETAIL

    def test_set_abstract_level(self):
        item = ContextItem(source_type="test", content="x", level=ContextLevel.ABSTRACT)
        assert item.level == ContextLevel.ABSTRACT

    def test_default_category_is_none(self):
        item = ContextItem(source_type="test", content="x")
        assert item.category is None

    def test_set_category(self):
        item = ContextItem(source_type="test", content="x", category=MemoryCategory.PREFERENCES)
        assert item.category == MemoryCategory.PREFERENCES

    def test_active_count_defaults_to_zero(self):
        item = ContextItem(source_type="test", content="x")
        assert item.active_count == 0

    def test_updated_at_is_datetime(self):
        item = ContextItem(source_type="test", content="x")
        assert isinstance(item.updated_at, datetime)

    def test_all_memory_categories_valid(self):
        for cat in MemoryCategory:
            item = ContextItem(source_type="test", content="x", category=cat)
            assert item.category == cat

    def test_all_context_levels_valid(self):
        for level in ContextLevel:
            item = ContextItem(source_type="test", content="x", level=level)
            assert item.level == level


# ── ContextAggregator category_filter and max_level ───────────────────────────

def _make_items(*specs: tuple[str | None, str]) -> list[ContextItem]:
    """Build ContextItems from (category_or_none, level) pairs."""
    level_map = {"abstract": ContextLevel.ABSTRACT, "overview": ContextLevel.OVERVIEW, "detail": ContextLevel.DETAIL}
    cat_map = {c.value: c for c in MemoryCategory}
    items = []
    for cat_str, level_str in specs:
        items.append(ContextItem(
            source_type="test",
            content=f"content-{cat_str}-{level_str}",
            category=cat_map.get(cat_str) if cat_str else None,
            level=level_map[level_str],
            score=0.9,
        ))
    return items


class TestContextAggregatorCategoryFilter:
    @pytest.mark.asyncio
    async def test_category_filter_excludes_non_matching(self):
        items = _make_items(("profile", "detail"), ("events", "detail"), (None, "detail"))
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = items
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1",
            session_id="sess",
            query="test",
            category_filter=[MemoryCategory.PROFILE],
        )
        snap = await agg.aggregate(request)
        categories = {i.category for i in snap.items}
        # Only PROFILE and None (uncategorised) should pass
        assert MemoryCategory.EVENTS not in categories

    @pytest.mark.asyncio
    async def test_no_category_filter_returns_all(self):
        items = _make_items(("profile", "detail"), ("events", "detail"), (None, "detail"))
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = items
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1", session_id="sess", query="test", category_filter=None
        )
        snap = await agg.aggregate(request)
        assert len(snap.items) == 3


class TestContextAggregatorLevelFilter:
    @pytest.mark.asyncio
    async def test_max_level_abstract_filters_overview_and_detail(self):
        items = _make_items(
            (None, "abstract"), (None, "overview"), (None, "detail")
        )
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = items
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1",
            session_id="sess",
            query="test",
            max_level=ContextLevel.ABSTRACT,
        )
        snap = await agg.aggregate(request)
        assert all(i.level == ContextLevel.ABSTRACT for i in snap.items)

    @pytest.mark.asyncio
    async def test_max_level_detail_returns_all(self):
        items = _make_items(
            (None, "abstract"), (None, "overview"), (None, "detail")
        )
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = items
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1",
            session_id="sess",
            query="test",
            max_level=ContextLevel.DETAIL,
        )
        snap = await agg.aggregate(request)
        assert len(snap.items) == 3


class TestContextAggregatorMode:
    @pytest.mark.asyncio
    async def test_fast_mode_calls_standard_search(self):
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = []
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1", session_id="sess", query="test", mode="fast"
        )
        await agg.aggregate(request)
        ltm_mock.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_quality_mode_falls_back_to_standard_when_no_agentic(self):
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = []
        # No agentic_search attribute → should fall back to search
        del ltm_mock.agentic_search
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1", session_id="sess", query="test", mode="quality"
        )
        await agg.aggregate(request)
        ltm_mock.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_quality_mode_uses_agentic_when_available(self):
        ltm_mock = AsyncMock()
        ltm_mock.search.return_value = []
        ltm_mock.agentic_search = AsyncMock(return_value=[])
        agg = ContextAggregator(ltm=ltm_mock)
        request = AggregationRequest(
            scope_id="s1", session_id="sess", query="test", mode="quality"
        )
        await agg.aggregate(request)
        ltm_mock.agentic_search.assert_called_once()
        ltm_mock.search.assert_not_called()


# ── WorkingMemoryManager.mark_used ────────────────────────────────────────────

class TestWorkingMemoryMarkUsed:
    @pytest.mark.asyncio
    async def test_mark_used_increments_active_count(self):
        wm = WorkingMemoryManager()  # in-process (no Redis)
        note = WorkingNote(
            scope_id="s1",
            session_id="sess",
            note_type=NoteType.TASK_PLAN,
            content={"steps": ["step1"]},
        )
        note = await wm.create_note(note)
        updated = await wm.mark_used("s1", "sess", [note.note_id])
        assert updated == 1
        # Verify _active_count incremented in content
        notes = await wm.list_notes("s1", "sess")
        matching = [n for n in notes if n.note_id == note.note_id]
        assert matching[0].content.get("_active_count") == 1

    @pytest.mark.asyncio
    async def test_mark_used_unknown_id_returns_zero(self):
        wm = WorkingMemoryManager()
        updated = await wm.mark_used("s1", "sess", ["nonexistent-id"])
        assert updated == 0

    @pytest.mark.asyncio
    async def test_mark_used_empty_ids_returns_zero(self):
        wm = WorkingMemoryManager()
        updated = await wm.mark_used("s1", "sess", [])
        assert updated == 0


# ── ToolContextGovernor tool stats ────────────────────────────────────────────

class TestToolGovernorStats:
    def _make_governor(self) -> ToolContextGovernor:
        tools = [
            ToolDefinition(tool_id="t1", name="Tool1", description="desc"),
            ToolDefinition(tool_id="t2", name="Tool2", description="desc"),
        ]
        return ToolContextGovernor(tools=tools)

    def test_record_tool_result_success(self):
        gov = self._make_governor()
        gov.record_tool_result("t1", success=True, duration_ms=50.0)
        stats = gov._tools["t1"].metadata["tool_stats"]
        assert stats["call_time"] == 1
        assert stats["success_time"] == 1

    def test_record_tool_result_failure(self):
        gov = self._make_governor()
        gov.record_tool_result("t1", success=False, duration_ms=100.0)
        stats = gov._tools["t1"].metadata["tool_stats"]
        assert stats["call_time"] == 1
        assert stats["success_time"] == 0

    def test_success_rate_no_calls_is_one(self):
        gov = self._make_governor()
        assert gov._success_rate(gov._tools["t1"]) == 1.0

    def test_success_rate_partial(self):
        gov = self._make_governor()
        gov.record_tool_result("t1", success=True, duration_ms=10.0)
        gov.record_tool_result("t1", success=False, duration_ms=10.0)
        assert gov._success_rate(gov._tools["t1"]) == pytest.approx(0.5)

    def test_unknown_tool_id_logs_warning(self):
        """Unknown tool_id should not raise."""
        gov = self._make_governor()
        gov.record_tool_result("unknown_tool", success=True, duration_ms=10.0)

    def test_sort_by_success_rate(self):
        gov = self._make_governor()
        # t1 = 100% success, t2 = 0% success
        gov.record_tool_result("t1", success=True, duration_ms=10.0)
        gov.record_tool_result("t2", success=False, duration_ms=10.0)
        sorted_tools = gov._sort_by_success_rate(list(gov._tools.values()))
        assert sorted_tools[0].tool_id == "t1"
        assert sorted_tools[1].tool_id == "t2"

    @pytest.mark.asyncio
    async def test_select_tools_small_set_sorted_by_success_rate(self):
        gov = self._make_governor()
        # Give t2 a high success rate and t1 a low one
        gov.record_tool_result("t1", success=False, duration_ms=10.0)
        gov.record_tool_result("t2", success=True, duration_ms=10.0)
        selected = await gov.select_tools("s1", "any task", top_k=2)
        # t2 should come first (higher success rate)
        assert selected[0].tool_id == "t2"


# ── RRF hotness integration ────────────────────────────────────────────────────

class TestRRFFusionHotness:
    def test_hot_item_ranks_higher(self):
        """An item with high active_count should rank above a cold item with same position."""
        from context_agent.core.retrieval.search_coordinator import UnifiedSearchCoordinator

        hot_item = ContextItem(
            source_type="test",
            content="hot content",
            active_count=50,
            updated_at=datetime.now(tz=timezone.utc),
        )
        cold_item = ContextItem(
            source_type="test",
            content="cold content",
            active_count=0,
            updated_at=datetime.now(tz=timezone.utc) - timedelta(days=30),
        )

        # Both appear at same rank-0 position in a single list → RRF score identical
        # Hotness blending should differentiate them
        fused = UnifiedSearchCoordinator._rrf_fuse([[hot_item, cold_item]])
        assert fused[0].item_id == hot_item.item_id  # hot item ranks first

    def test_fuse_empty_lists(self):
        from context_agent.core.retrieval.search_coordinator import UnifiedSearchCoordinator
        assert UnifiedSearchCoordinator._rrf_fuse([]) == []
        assert UnifiedSearchCoordinator._rrf_fuse([[]]) == []
