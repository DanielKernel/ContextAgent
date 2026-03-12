"""Hotness Score — time-decay relevance scoring for context items.

Adapted from OpenViking memory_lifecycle.py.

Formula:
    hotness = sigmoid(log1p(active_count)) × exp(-λ × age_days)
    λ = ln(2) / half_life_days

    active_count  — number of confirmed uses (incremented via used() feedback API)
    age_days      — days since last update
    half_life_days — default 7: hotness halves every 7 days of non-use

The final score is blended into RRF fusion at HOTNESS_ALPHA weight (default 0.2).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

HOTNESS_ALPHA: float = 0.2  # blend weight in RRF fusion
DEFAULT_HALF_LIFE_DAYS: float = 7.0


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def compute_hotness(
    active_count: int | None,
    updated_at: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Return a hotness score in [0, 1].

    Args:
        active_count: Number of confirmed uses of this context item.
        updated_at:   Timestamp of last update (UTC). Defaults to now (age=0).
        half_life_days: Decay half-life in days. Smaller = faster decay.

    Returns:
        float in [0, 1]: 0 = cold/never used, approaching 1 = very hot.
    """
    if active_count is None:
        active_count = 0
    elif not isinstance(active_count, int):
        raise TypeError("active_count must be an int or None")

    if half_life_days <= 0:
        raise ValueError("half_life_days must be greater than 0")

    if active_count < 0:
        active_count = 0

    frequency_score = _sigmoid(math.log1p(active_count))

    if updated_at is None:
        age_days = 0.0
    else:
        now = datetime.now(tz=timezone.utc)
        # Normalise tz-naive datetimes to UTC
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        delta = now - updated_at
        age_days = max(0.0, delta.total_seconds() / 86400.0)

    decay_lambda = math.log(2.0) / half_life_days
    recency_score = math.exp(-decay_lambda * age_days)

    return frequency_score * recency_score


def hotness_blend(semantic_score: float, hotness: float, alpha: float = HOTNESS_ALPHA) -> float:
    """Blend semantic relevance with hotness.

    result = (1 - alpha) * semantic_score + alpha * hotness
    """
    alpha = max(0.0, min(1.0, alpha))
    return (1.0 - alpha) * semantic_score + alpha * hotness
