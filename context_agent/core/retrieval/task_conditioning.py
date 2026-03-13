"""Task-conditioned scoring helpers for retrieval and aggregation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from context_agent.models.context import ContextItem, ContextLevel, MemoryCategory, MemoryType


def apply_task_conditioning(
    items: Sequence[ContextItem],
    *,
    task_type: str = "",
    agent_role: str = "",
) -> list[ContextItem]:
    """Return items reordered with lightweight task-aware score adjustments."""
    if not task_type and not agent_role:
        return list(items)

    conditioned: list[ContextItem] = []
    for item in items:
        adjusted = _conditioned_score(item, task_type=task_type, agent_role=agent_role)
        conditioned.append(item.model_copy(update={"score": adjusted}))

    return sorted(conditioned, key=lambda item: item.score, reverse=True)


def _conditioned_score(item: ContextItem, *, task_type: str, agent_role: str) -> float:
    score = item.score
    task = task_type.strip().lower()
    role = agent_role.strip().lower()

    memory_type = item.memory_type
    category = item.category
    level = item.level
    tier = item.tier
    metadata = item.metadata

    if task == "qa":
        score += _match_bonus(
            memory_type,
            {MemoryType.SEMANTIC: 0.12, MemoryType.EPISODIC: 0.05},
        )
        score += _match_bonus(
            category,
            {MemoryCategory.PROFILE: 0.08, MemoryCategory.PREFERENCES: 0.08},
        )
        if tier in {"warm", "cold"}:
            score += 0.03
        if memory_type == MemoryType.VARIABLE:
            score -= 0.03
    elif task == "task":
        score += _match_bonus(
            memory_type,
            {
                MemoryType.VARIABLE: 0.12,
                MemoryType.PROCEDURAL: 0.12,
                MemoryType.EPISODIC: 0.03,
            },
        )
        score += _match_bonus(category, {MemoryCategory.PATTERNS: 0.10, MemoryCategory.CASES: 0.08})
        if tier == "hot":
            score += 0.08
        if level == ContextLevel.DETAIL:
            score += 0.04
    elif task == "long_session":
        score += _match_bonus(memory_type, {MemoryType.EPISODIC: 0.12, MemoryType.SEMANTIC: 0.04})
        score += _match_bonus(category, {MemoryCategory.EVENTS: 0.10})
        score += _match_bonus(level, {ContextLevel.OVERVIEW: 0.06, ContextLevel.ABSTRACT: 0.04})
    elif task == "realtime":
        score += _match_bonus(memory_type, {MemoryType.VARIABLE: 0.12, MemoryType.PROCEDURAL: 0.04})
        if tier == "hot":
            score += 0.15
        if level == ContextLevel.ABSTRACT:
            score += 0.05
        if level == ContextLevel.DETAIL:
            score -= 0.08
        if tier == "cold":
            score -= 0.05
    elif task == "compaction":
        score += _match_bonus(level, {ContextLevel.ABSTRACT: 0.12, ContextLevel.OVERVIEW: 0.10})
        score += _match_bonus(memory_type, {MemoryType.EPISODIC: 0.04, MemoryType.SEMANTIC: 0.04})
        if level == ContextLevel.DETAIL:
            score -= 0.06

    if role == "planner":
        score += _match_bonus(level, {ContextLevel.ABSTRACT: 0.08, ContextLevel.OVERVIEW: 0.08})
        score += _match_bonus(memory_type, {MemoryType.SEMANTIC: 0.05, MemoryType.PROCEDURAL: 0.05})
    elif role == "executor":
        if tier == "hot":
            score += 0.08
        score += _match_bonus(memory_type, {MemoryType.VARIABLE: 0.08, MemoryType.PROCEDURAL: 0.08})
    elif role == "reviewer":
        score += _match_bonus(
            category,
            {MemoryCategory.CASES: 0.08, MemoryCategory.PATTERNS: 0.08},
        )
        score += _match_bonus(memory_type, {MemoryType.EPISODIC: 0.05})
        score -= _match_bonus(
            category,
            {MemoryCategory.PROFILE: 0.05, MemoryCategory.PREFERENCES: 0.05},
        )

    score += _metadata_bonus(metadata, key="task_type", expected=task, bonus=0.10)
    score += _metadata_bonus(metadata, key="agent_role", expected=role, bonus=0.08)
    score += _metadata_membership_bonus(
        metadata,
        key="required_for_task_types",
        expected=task,
        bonus=0.10,
    )

    return max(0.0, min(1.0, score))


def _match_bonus(value: object | None, mapping: dict[object, float]) -> float:
    if value is None:
        return 0.0
    return mapping.get(value, 0.0)


def _metadata_bonus(
    metadata: dict[str, Any],
    *,
    key: str,
    expected: str,
    bonus: float,
) -> float:
    if not expected:
        return 0.0
    value = metadata.get(key)
    if isinstance(value, str) and value.strip().lower() == expected:
        return bonus
    return 0.0


def _metadata_membership_bonus(
    metadata: dict[str, Any],
    *,
    key: str,
    expected: str,
    bonus: float,
) -> float:
    if not expected:
        return 0.0
    value = metadata.get(key)
    if isinstance(value, str):
        return bonus if value.strip().lower() == expected else 0.0
    if isinstance(value, Sequence):
        return bonus if any(str(member).strip().lower() == expected for member in value) else 0.0
    return 0.0
