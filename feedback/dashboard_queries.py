"""Read-only queries for the Feedback Loop dashboard (separate from core store)."""

from __future__ import annotations

import json
from typing import Optional

import psycopg

from feedback.generate import FEEDBACK_VERSION
from feedback.schemas import ClusterStats, FeedbackPayload, FeedbackRecord


def count_feedback_coverage(
    conn: psycopg.Connection,
    *,
    feedback_version: str = FEEDBACK_VERSION,
) -> dict[str, int]:
    """Counts for dashboard: validated, with feedback, missing feedback."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE p.status = 'validated'
                      AND p.prediction_delta IS NOT NULL
                ) AS validated,
                COUNT(f.feedback_id) FILTER (
                    WHERE p.status = 'validated'
                      AND p.prediction_delta IS NOT NULL
                ) AS with_feedback
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            """,
            (feedback_version,),
        )
        row = cur.fetchone()
    validated = int(row[0] or 0) if row else 0
    with_feedback = int(row[1] or 0) if row else 0
    return {
        "validated": validated,
        "with_feedback": with_feedback,
        "missing_feedback": max(0, validated - with_feedback),
    }


def list_clusters(
    conn: psycopg.Connection,
    *,
    limit: int = 100,
) -> list[ClusterStats]:
    """All prediction_clusters ordered by sample_count desc."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, label, sample_count, mean_delta, std_delta
            FROM prediction_clusters
            ORDER BY sample_count DESC, cluster_id ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        ClusterStats(
            cluster_id=row[0],
            label=row[1],
            sample_count=int(row[2] or 0),
            mean_delta=float(row[3]) if row[3] is not None else None,
            std_delta=float(row[4]) if row[4] is not None else None,
        )
        for row in rows
    ]


def list_recent_feedback(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
    cluster_id: Optional[str] = None,
    feedback_version: str = FEEDBACK_VERSION,
) -> list[FeedbackRecord]:
    """Recent feedback rows for dashboard tables."""
    params: list = [feedback_version]
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND f.cluster_id = %s"
        params.append(cluster_id)
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT f.feedback_id, f.prediction_id, f.cluster_id, f.feedback_json,
                   f.feedback_version, f.generated_at, f.generation_method
            FROM prediction_feedback f
            WHERE f.feedback_version = %s
              {cluster_clause}
            ORDER BY f.generated_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_row_to_feedback_record(row) for row in rows]


def _row_to_feedback_record(row: tuple) -> FeedbackRecord:
    feedback_json = row[3]
    if isinstance(feedback_json, str):
        feedback_json = json.loads(feedback_json)
    payload = FeedbackPayload.model_validate(feedback_json)
    return FeedbackRecord(
        feedback_id=row[0],
        prediction_id=row[1],
        cluster_id=row[2],
        feedback_json=payload,
        feedback_version=row[4],
        generated_at=row[5],
        generation_method=row[6],
    )
