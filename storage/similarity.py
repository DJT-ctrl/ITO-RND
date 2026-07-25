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
) -> list[dict[str, Any]]:
    """Return the ``limit`` posts closest to ``query_vector`` (cosine distance).

    Uses the halfvec(3072) HNSW index. Tenant scoping: if ``user_id`` is set,
    search that subscriber first; cold-start falls back to the global corpus
    when fewer than ``min_user_results`` rows return.

    T10.8: when ``prefer_niche`` is a valid taxonomy id and soft prefer is on,
    over-fetch then re-rank same-niche neighbors ahead of others. Never
    hard-filters to niche-only results.
    """
    niche = prefer_niche if is_valid_niche(prefer_niche) else None
    use_soft = bool(soft_topic_prefer and niche)
    fetch_limit = limit
    if use_soft:
        fetch_limit = min(max(limit * max(1, overfetch_factor), limit), _SOFT_TOPIC_OVERFETCH_CAP)

    rows = _find_similar_query(conn, query_vector, fetch_limit, user_id)
    if user_id is not None and len(rows) < min_user_results and fallback_to_global:
        rows = _find_similar_query(conn, query_vector, fetch_limit, user_id=None)

    if use_soft:
        return apply_soft_topic_prefer(rows, niche, limit)
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
        niche = row.get("niche")
        match = 0 if isinstance(niche, str) and niche == prefer_niche else 1
        distance = row.get("cosine_distance")
        try:
            dist_f = float(distance) if distance is not None else float("inf")
        except (TypeError, ValueError):
            dist_f = float("inf")
        return match, dist_f

    # Stable: Python's sort is stable; we only add niche priority as primary key.
    ranked = sorted(rows, key=_sort_key)
    return ranked[:limit]
