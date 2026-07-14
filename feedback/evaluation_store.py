"""Database reads for leakage-safe feedback-loop replay."""

from __future__ import annotations

import psycopg

from feedback.evaluation import ReplayRow
from feedback.generate import FEEDBACK_VERSION, FEEDBACK_VERSION_V2


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
                ) AS cluster_id,
                EXISTS (
                    SELECT 1
                    FROM prediction_feedback fv2
                    WHERE fv2.prediction_id = p.prediction_id
                      AND fv2.feedback_version = %s
                      AND fv2.feedback_review_status = 'approved'
                ) AS has_approved_v2,
                p.predicted_engagement_percentile AS live_percentile,
                (p.prediction_telemetry->>'shadow_percentile')::DOUBLE PRECISION
                    AS shadow_percentile,
                (p.prediction_telemetry->>'llm_percentile')::DOUBLE PRECISION
                    AS llm_percentile
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            WHERE p.status = 'validated'
              AND p.actual_engagement_percentile IS NOT NULL
            ORDER BY p.prediction_id
            """,
            (FEEDBACK_VERSION_V2, feedback_version),
        )
        rows = cur.fetchall()
    return [
        ReplayRow(
            prediction_id=row[0],
            actual_percentile=float(row[1]),
            raw_percentile=float(row[2]),
            cluster_id=row[3],
            has_approved_v2=bool(row[4]),
            live_percentile=float(row[5]) if row[5] is not None else None,
            shadow_percentile=float(row[6]) if row[6] is not None else None,
            llm_percentile=float(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]
