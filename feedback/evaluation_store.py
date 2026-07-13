"""Database reads for leakage-safe feedback-loop replay."""

from __future__ import annotations

import psycopg

from feedback.evaluation import ReplayRow
from feedback.generate import FEEDBACK_VERSION


def fetch_replay_rows(
    conn: psycopg.Connection,
    *,
    feedback_version: str = FEEDBACK_VERSION,
) -> list[ReplayRow]:
    """Load validated rows with the raw score captured at prediction time."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.prediction_id,
                p.actual_engagement_percentile,
                COALESCE(
                    (p.prediction_telemetry->>'raw_percentile')::DOUBLE PRECISION,
                    p.predicted_engagement_percentile
                ) AS raw_percentile,
                COALESCE(
                    NULLIF(p.prediction_telemetry->>'cluster_id', ''),
                    f.cluster_id
                ) AS cluster_id
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            WHERE p.status = 'validated'
              AND p.actual_engagement_percentile IS NOT NULL
            ORDER BY p.prediction_id
            """,
            (feedback_version,),
        )
        rows = cur.fetchall()
    return [
        ReplayRow(
            prediction_id=row[0],
            actual_percentile=float(row[1]),
            raw_percentile=float(row[2]),
            cluster_id=row[3],
        )
        for row in rows
    ]
