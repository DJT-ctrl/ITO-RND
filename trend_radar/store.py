"""Postgres read/write for A2 trends."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import numpy as np
import psycopg
from psycopg.rows import dict_row

from trend_radar.schemas import CorpusPostVector, TrendRow

_FETCH_WINDOW_SQL = """
SELECT
    post_id,
    embedding,
    total_engagement,
    topic,
    content
FROM posts
WHERE engagement_anomaly_flag = FALSE
  AND inserted_at >= %s
  AND inserted_at < %s
"""

_FETCH_PREV_TRENDS_SQL = """
SELECT cluster_id, centroid, post_count
FROM trends
WHERE week_start = %s
  AND source = 'corpus'
  AND centroid IS NOT NULL
"""

_UPSERT_SQL = """
INSERT INTO trends (
    week_start,
    cluster_id,
    label,
    post_count,
    share_of_corpus,
    growth_rate,
    mean_total_engagement,
    example_post_ids,
    centroid,
    source
) VALUES (
    %(week_start)s,
    %(cluster_id)s,
    %(label)s,
    %(post_count)s,
    %(share_of_corpus)s,
    %(growth_rate)s,
    %(mean_total_engagement)s,
    %(example_post_ids)s,
    %(centroid)s,
    %(source)s
)
ON CONFLICT (week_start, cluster_id) DO UPDATE SET
    label = EXCLUDED.label,
    post_count = EXCLUDED.post_count,
    share_of_corpus = EXCLUDED.share_of_corpus,
    growth_rate = EXCLUDED.growth_rate,
    mean_total_engagement = EXCLUDED.mean_total_engagement,
    example_post_ids = EXCLUDED.example_post_ids,
    centroid = EXCLUDED.centroid,
    source = EXCLUDED.source,
    computed_at = now()
"""

_LIST_SQL = """
SELECT
    trend_id,
    week_start,
    cluster_id,
    label,
    post_count,
    share_of_corpus,
    growth_rate,
    mean_total_engagement,
    example_post_ids,
    source,
    computed_at
FROM trends
WHERE source = 'corpus'
ORDER BY week_start DESC, growth_rate DESC NULLS LAST
LIMIT %s
"""


def _as_vector(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value.astype(np.float64)
    return np.asarray(list(value), dtype=np.float64)


def fetch_corpus_posts_in_window(
    conn: psycopg.Connection,
    start: datetime,
    end: datetime,
) -> list[CorpusPostVector]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FETCH_WINDOW_SQL, (start, end))
        rows = cur.fetchall()
    out: list[CorpusPostVector] = []
    for r in rows:
        out.append(
            CorpusPostVector(
                post_id=r["post_id"],
                embedding=_as_vector(r["embedding"]),
                total_engagement=int(r["total_engagement"]),
                topic=r["topic"],
                content=r["content"] or "",
            )
        )
    return out


def fetch_previous_centroids(
    conn: psycopg.Connection,
    week_start: date,
) -> list[tuple[str, np.ndarray, int]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FETCH_PREV_TRENDS_SQL, (week_start,))
        rows = cur.fetchall()
    return [
        (r["cluster_id"], _as_vector(r["centroid"]), int(r["post_count"]))
        for r in rows
        if r["centroid"] is not None
    ]


def upsert_trend_rows(conn: psycopg.Connection, rows: list[TrendRow]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                _UPSERT_SQL,
                {
                    "week_start": row.week_start,
                    "cluster_id": row.cluster_id,
                    "label": row.label,
                    "post_count": row.post_count,
                    "share_of_corpus": row.share_of_corpus,
                    "growth_rate": row.growth_rate,
                    "mean_total_engagement": row.mean_total_engagement,
                    "example_post_ids": row.example_post_ids,
                    "centroid": row.centroid,
                    "source": row.source,
                },
            )
    conn.commit()
    return len(rows)


def list_trends(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LIST_SQL, (limit,))
        rows = cur.fetchall()
    return [
        {
            "trend_id": str(r["trend_id"]),
            "week_start": str(r["week_start"]),
            "cluster_id": r["cluster_id"],
            "label": r["label"],
            "post_count": int(r["post_count"]),
            "share_of_corpus": float(r["share_of_corpus"]),
            "growth_rate": (
                None if r["growth_rate"] is None else float(r["growth_rate"])
            ),
            "mean_total_engagement": (
                None
                if r["mean_total_engagement"] is None
                else float(r["mean_total_engagement"])
            ),
            "example_post_ids": list(r["example_post_ids"] or []),
            "source": r["source"],
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]
