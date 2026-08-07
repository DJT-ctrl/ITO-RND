"""Nearest-neighbour retrieval against posts embeddings (T2.2 + T10.8).

Extracted from ``storage.vector_store`` so connection/upsert stay separate
from ranking logic. Public callers may still import ``find_similar`` from
``storage.vector_store`` (re-export) for backward compatibility.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import psycopg

from phase_10.topics import is_valid_niche

# Cap over-fetch so soft prefer never scans unbounded rows.
_SOFT_TOPIC_OVERFETCH_CAP = 50

# --- T2.2 nearest-neighbour retrieval ---
# Columns returned by find_similar(), in SELECT order (excluding the
# computed cosine_distance, added separately below). follower_count/
# engagement_rate/audience_adjusted_percentile are the optional T6 Point 1
# follower-normalization fields — NULL when that path never touched the
# post, so callers must treat them as optional.
_SIMILAR_COLUMNS = [
    "post_id",
    "linkedin_url",
    "content",
    "likes",
    "comments",
    "shares",
    "total_engagement",
    "engagement_percentile",
    "engagement_zscore",
    "follower_count",
    "engagement_rate",
    "audience_adjusted_percentile",
    "hashtag_count",
    "word_count",
    "topic",
    "niche",
    "hook_type",
    "engagement_anomaly_flag",
    "posted_at",
    "engagement_age_hours",
]


def find_similar(
    conn: psycopg.Connection,
    query_vector: np.ndarray,
    limit: int = 10,
    user_id: Optional[str] = None,
    fallback_to_global: bool = True,
    min_user_results: int = 3,
    *,
    prefer_niche: Optional[str] = None,
    soft_topic_prefer: bool = True,
    overfetch_factor: int = 3,
    prefer_age_hours: Optional[float] = None,
    soft_age_prefer: bool = True,
) -> list[dict[str, Any]]:
    """Return the ``limit`` posts closest to ``query_vector`` (cosine distance).

    Uses the halfvec(3072) HNSW index. Tenant scoping: if ``user_id`` is set,
    search that subscriber first; cold-start falls back to the global corpus
    when fewer than ``min_user_results`` rows return.

    T10.8: when ``prefer_niche`` is a valid taxonomy id and soft prefer is on,
    over-fetch then re-rank same-niche neighbors ahead of others. Never
    hard-filters to niche-only results.

    Phase 11: when ``prefer_age_hours`` is set and soft age prefer is on,
    over-fetch then re-rank same age-bucket neighbors ahead of others.
    """
    niche = prefer_niche if is_valid_niche(prefer_niche) else None
    use_soft_topic = bool(soft_topic_prefer and niche)
    use_soft_age = bool(soft_age_prefer and prefer_age_hours is not None)
    fetch_limit = limit
    if use_soft_topic or use_soft_age:
        fetch_limit = min(max(limit * max(1, overfetch_factor), limit), _SOFT_TOPIC_OVERFETCH_CAP)

    rows = _find_similar_query(conn, query_vector, fetch_limit, user_id)
    if user_id is not None and len(rows) < min_user_results and fallback_to_global:
        rows = _find_similar_query(conn, query_vector, fetch_limit, user_id=None)

    if use_soft_topic and use_soft_age:
        # Applying these as two independent sequential stable-sorts would let
        # the second sort's key dominate and silently discard the first
        # preference's effect on the final order (see
        # apply_soft_topic_and_age_prefer's docstring). Combine into one key
        # instead so niche and age preference are both honored.
        rows = apply_soft_topic_and_age_prefer(rows, niche, float(prefer_age_hours), limit)
    elif use_soft_topic:
        rows = apply_soft_topic_prefer(rows, niche, limit)
    elif use_soft_age:
        rows = apply_soft_age_prefer(rows, float(prefer_age_hours), limit)
    return rows[:limit] if len(rows) > limit else rows


def _find_similar_query(
    conn: psycopg.Connection,
    query_vector: np.ndarray,
    limit: int,
    user_id: Optional[str],
) -> list[dict[str, Any]]:
    """Run the actual cosine-distance query, optionally filtered by user_id."""
    select_clause = ", ".join(_SIMILAR_COLUMNS)
    where_clause = "WHERE user_id = %s " if user_id is not None else ""
    sql = (
        f"SELECT {select_clause}, "
        f"embedding::halfvec(3072) <=> %s::halfvec(3072) AS cosine_distance "
        f"FROM posts "
        f"{where_clause}"
        f"ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) "
        f"LIMIT %s"
    )
    params = (
        (query_vector, user_id, query_vector, limit)
        if user_id is not None
        else (query_vector, query_vector, limit)
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


# --- T10.8 soft topic preference (re-rank only; never hard-filter) ---


def apply_soft_topic_prefer(
    rows: list[dict[str, Any]],
    prefer_niche: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Stable re-rank: same-niche first, then cosine_distance; truncate to limit.

    Does not drop non-matching niches — thin niches still get global neighbors.
    """
    if limit <= 0:
        return []
    if not rows:
        return []
    if not is_valid_niche(prefer_niche):
        return rows[:limit]

    def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
        return _niche_match(row, prefer_niche), _distance(row)

    # Stable: Python's sort is stable; we only add niche priority as primary key.
    ranked = sorted(rows, key=_sort_key)
    return ranked[:limit]


def apply_soft_age_prefer(
    rows: list[dict[str, Any]],
    prefer_age_hours: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Stable re-rank: same age-bucket first, then cosine_distance."""
    if limit <= 0:
        return []
    if not rows:
        return []

    def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
        return _age_match(row, prefer_age_hours), _distance(row)

    ranked = sorted(rows, key=_sort_key)
    return ranked[:limit]


def apply_soft_topic_and_age_prefer(
    rows: list[dict[str, Any]],
    prefer_niche: str | None,
    prefer_age_hours: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Stable re-rank preferring niche match *and* age-bucket match together.

    Niche prefer and age prefer are each single-key stable sorts. Calling
    them back-to-back (sort by niche, then re-sort the result by age) does
    not compose: the second sort re-orders every row by its own key alone,
    so it silently overrides — not augments — the first sort's effect on
    the final order. Whenever both a niche and a horizon are supplied (the
    normal Phase 11 predict-time case, since posts usually have a niche),
    that regressed niche soft-prefer back to age-only ranking.

    Instead, rank by how many of the two preferences each row matches (0, 1,
    or 2 mismatches) as a single combined key, then cosine_distance as the
    tie-breaker. Neither preference is treated as more important than the
    other; a row matching both outranks a row matching only one, which
    outranks a row matching neither.
    """
    if limit <= 0:
        return []
    if not rows:
        return []
    niche = prefer_niche if is_valid_niche(prefer_niche) else None

    def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
        mismatches = _niche_match(row, niche) + _age_match(row, prefer_age_hours)
        return mismatches, _distance(row)

    ranked = sorted(rows, key=_sort_key)
    return ranked[:limit]


def _niche_match(row: dict[str, Any], niche: str | None) -> int:
    """0 if row's niche matches (a valid) *niche*, else 1."""
    if not niche:
        return 1
    row_niche = row.get("niche")
    return 0 if isinstance(row_niche, str) and row_niche == niche else 1


def _age_match(row: dict[str, Any], prefer_age_hours: float) -> int:
    """0 if row's engagement age falls in the same bucket as *prefer_age_hours*."""
    from validation_pipeline.age_buckets import bucket_for_hours

    age = row.get("engagement_age_hours")
    try:
        age_f = float(age) if age is not None else None
    except (TypeError, ValueError):
        age_f = None
    if age_f is None:
        return 1
    return 0 if bucket_for_hours(age_f) == bucket_for_hours(prefer_age_hours) else 1


def _distance(row: dict[str, Any]) -> float:
    """cosine_distance as a float, or +inf when missing/invalid (sorts last)."""
    distance = row.get("cosine_distance")
    try:
        return float(distance) if distance is not None else float("inf")
    except (TypeError, ValueError):
        return float("inf")
