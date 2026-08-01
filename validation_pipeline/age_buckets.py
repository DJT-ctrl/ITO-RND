"""Age buckets for multi-horizon validation (Phase 11).

Buckets group posts / predictions by engagement age so percentiles, neighbor
prefer, and learning filters compare like with like.
"""

from __future__ import annotations

from typing import Optional, Sequence

# (bucket_id, low_inclusive, high_exclusive). Last bucket is open-ended.
_BUCKET_EDGES: tuple[tuple[str, float, float | None], ...] = (
    ("0_6", 0.0, 6.0),
    ("6_12", 6.0, 12.0),
    ("12_24", 12.0, 24.0),
    ("24_36", 24.0, 36.0),
    ("36_48", 36.0, 48.0),
    ("48_72", 48.0, 72.0),
    ("72_168", 72.0, 168.0),
    ("168_plus", 168.0, None),
)

DEFAULT_AGE_BUCKET_MIN_N = 30
FIXED_HORIZONS_HOURS = (24, 48, 72)
LANE_SAME_AGE = "same_age"
LANE_FIXED_HORIZON = "fixed_horizon"


def bucket_for_hours(hours: float | None) -> str:
    """Return bucket id for a non-negative age/horizon in hours."""
    if hours is None:
        return "unknown"
    age = max(0.0, float(hours))
    for bucket_id, low, high in _BUCKET_EDGES:
        if high is None:
            if age >= low:
                return bucket_id
            continue
        if low <= age < high:
            return bucket_id
    return "168_plus"


def bucket_bounds(bucket_id: str) -> tuple[float, float | None] | None:
    """Return (low, high_exclusive) for a known bucket id."""
    for bid, low, high in _BUCKET_EDGES:
        if bid == bucket_id:
            return low, high
    return None


def all_bucket_ids() -> list[str]:
    return [bid for bid, _, _ in _BUCKET_EDGES]


def same_age_horizon_hours(age_hours: float) -> int:
    """Integer horizon for Lane A (at least 1 hour)."""
    return max(1, int(round(float(age_hours))))


def parse_fixed_horizons(raw: Sequence[int] | None = None) -> tuple[int, ...]:
    if not raw:
        return FIXED_HORIZONS_HOURS
    cleaned = tuple(sorted({int(h) for h in raw if int(h) > 0}))
    return cleaned or FIXED_HORIZONS_HOURS


def hours_in_bucket(hours: float, bucket_id: str) -> bool:
    bounds = bucket_bounds(bucket_id)
    if bounds is None:
        return False
    low, high = bounds
    age = max(0.0, float(hours))
    if high is None:
        return age >= low
    return low <= age < high


def sql_engagement_age_filter(
    *,
    bucket_id: str,
    alias: str = "p",
    column: str = "engagement_age_hours",
) -> tuple[str, list[float]]:
    """SQL fragment + params restricting *column* to the bucket range."""
    bounds = bucket_bounds(bucket_id)
    if bounds is None:
        return "AND FALSE", []
    low, high = bounds
    col = f"{alias}.{column}" if alias else column
    if high is None:
        return f"AND {col} IS NOT NULL AND {col} >= %s", [low]
    return (
        f"AND {col} IS NOT NULL AND {col} >= %s AND {col} < %s",
        [low, high],
    )


def horizon_learning_sql(
    *,
    enabled: bool,
    query_horizon_hours: Optional[float],
    alias: str = "p",
) -> tuple[str, list]:
    """Restrict learning rows to the same horizon age bucket when enabled."""
    if not enabled or query_horizon_hours is None:
        return "", []
    bucket = bucket_for_hours(query_horizon_hours)
    bounds = bucket_bounds(bucket)
    if bounds is None:
        return "", []
    low, high = bounds
    col = f"{alias}.prediction_horizon_hours"
    if high is None:
        return f"AND {col} IS NOT NULL AND {col} >= %s", [low]
    return (
        f"AND {col} IS NOT NULL AND {col} >= %s AND {col} < %s",
        [low, high],
    )
