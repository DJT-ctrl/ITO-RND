"""Read-only queries for the Feedback Loop dashboard (separate from core store)."""

from __future__ import annotations

import json
from typing import Optional

import psycopg

from feedback.generate import FEEDBACK_VERSION
from feedback.schemas import (
    ClusterAccuracy,
    ClusterStats,
    FeedbackPayload,
    FeedbackRecord,
    LearningStatus,
)


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


def hybrid_feedback_cost_stats(conn: psycopg.Connection) -> dict[str, float | int]:
    """Aggregate hybrid (v2) LLM cost for ops: total and cost per 100 rows."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS hybrid_rows,
                COUNT(*) FILTER (
                    WHERE feedback_review_status = 'approved'
                ) AS approved_v2,
                COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                COALESCE(SUM(output_tokens), 0) AS total_output_tokens
            FROM prediction_feedback
            WHERE generation_method = 'hybrid'
               OR feedback_version = 'v2'
            """
        )
        row = cur.fetchone()
    hybrid_rows = int(row[0] or 0) if row else 0
    approved_v2 = int(row[1] or 0) if row else 0
    total_cost = float(row[2] or 0.0) if row else 0.0
    input_tokens = int(row[3] or 0) if row else 0
    output_tokens = int(row[4] or 0) if row else 0
    cost_per_100 = (
        round((total_cost / hybrid_rows) * 100.0, 6) if hybrid_rows > 0 else 0.0
    )
    return {
        "hybrid_rows": hybrid_rows,
        "approved_v2": approved_v2,
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "cost_per_100_usd": cost_per_100,
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


def list_cluster_accuracy(
    conn: psycopg.Connection,
    *,
    feedback_version: str = FEEDBACK_VERSION,
    limit: int = 100,
) -> list[ClusterAccuracy]:
    """Validated percentile accuracy grouped by the routed cluster."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH scored AS (
                SELECT
                    COALESCE(
                        NULLIF(p.prediction_telemetry->>'cluster_id', ''),
                        f.cluster_id,
                        'unknown'
                    ) AS cluster_id,
                    p.prediction_delta,
                    p.actual_engagement_percentile,
                    p.predicted_engagement_percentile,
                    p.prediction_telemetry
                FROM predictions p
                LEFT JOIN prediction_feedback f
                  ON f.prediction_id = p.prediction_id
                 AND f.feedback_version = %s
                WHERE p.status = 'validated'
                  AND p.prediction_delta IS NOT NULL
                  AND p.actual_engagement_percentile IS NOT NULL
            )
            SELECT
                cluster_id,
                COUNT(*) AS sample_count,
                AVG(ABS(prediction_delta)) AS mae,
                AVG(ABS(
                    actual_engagement_percentile
                    - COALESCE(
                        (prediction_telemetry->>'raw_percentile')::DOUBLE PRECISION,
                        predicted_engagement_percentile
                    )
                )) AS raw_mae,
                AVG(ABS(
                    actual_engagement_percentile
                    - COALESCE(
                        (prediction_telemetry->>'calibrated_percentile')::DOUBLE PRECISION,
                        predicted_engagement_percentile
                    )
                )) AS calibrated_mae,
                AVG(CASE WHEN ABS(prediction_delta) <= 10 THEN 1.0 ELSE 0.0 END) * 100
                    AS pct_within_10
            FROM scored
            GROUP BY cluster_id
            ORDER BY sample_count DESC, cluster_id ASC
            LIMIT %s
            """,
            (feedback_version, limit),
        )
        rows = cur.fetchall()
    return [
        ClusterAccuracy(
            cluster_id=row[0],
            sample_count=int(row[1] or 0),
            mae=_optional_round(row[2]),
            raw_mae=_optional_round(row[3]),
            calibrated_mae=_optional_round(row[4]),
            pct_within_10=_optional_round(row[5], digits=1),
        )
        for row in rows
    ]


def fetch_learning_status(conn: psycopg.Connection) -> LearningStatus:
    """Return gate inputs and the latest cluster-stat refresh timestamp."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM predictions
                 WHERE status = 'validated' AND prediction_delta IS NOT NULL),
                (SELECT MAX(updated_at) FROM prediction_clusters)
            """
        )
        row = cur.fetchone()
    if row is None:
        return LearningStatus()
    return LearningStatus(
        n_validated=int(row[0] or 0),
        last_cluster_refresh_at=row[1],
    )


def list_recent_feedback(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
    cluster_id: Optional[str] = None,
    feedback_version: Optional[str] = FEEDBACK_VERSION,
) -> list[FeedbackRecord]:
    """Recent feedback rows for dashboard tables.

    Pass ``feedback_version=None`` to include every version (v1 template + v2 hybrid).
    """
    params: list = []
    version_clause = ""
    if feedback_version:
        version_clause = "WHERE f.feedback_version = %s"
        params.append(feedback_version)
    else:
        version_clause = "WHERE TRUE"

    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND f.cluster_id = %s"
        params.append(cluster_id)
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT f.feedback_id, f.prediction_id, f.cluster_id, f.feedback_json,
                   f.feedback_version, f.generated_at, f.generation_method,
                   f.generation_latency_ms, f.input_tokens, f.output_tokens, f.cost_usd,
                   f.feedback_review_status, f.reviewed_at, f.reviewed_by
            FROM prediction_feedback f
            {version_clause}
              {cluster_clause}
            ORDER BY f.generated_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_row_to_feedback_record(row) for row in rows]


def lesson_phase_stats(
    conn: psycopg.Connection,
    *,
    cluster_id: Optional[str] = None,
) -> dict[str, int]:
    """Phase B (v1 template) vs Phase G (v2 hybrid) counts, optional bucket filter."""
    params: list = []
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND cluster_id = %s"
        params.append(cluster_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE feedback_version = 'v1'
                       OR generation_method = 'template'
                ) AS template_v1,
                COUNT(*) FILTER (
                    WHERE feedback_version = 'v2'
                       OR generation_method IN ('hybrid', 'llm')
                ) AS hybrid_v2,
                COUNT(*) FILTER (
                    WHERE feedback_version = 'v2'
                      AND feedback_review_status = 'pending'
                ) AS v2_pending,
                COUNT(*) FILTER (
                    WHERE feedback_version = 'v2'
                      AND feedback_review_status = 'approved'
                ) AS v2_approved,
                COUNT(*) FILTER (
                    WHERE feedback_version = 'v2'
                      AND feedback_review_status = 'rejected'
                ) AS v2_rejected,
                COUNT(DISTINCT prediction_id) FILTER (
                    WHERE feedback_version = 'v2'
                ) AS predictions_with_v2
            FROM prediction_feedback
            WHERE TRUE
              {cluster_clause}
            """,
            params,
        )
        row = cur.fetchone()
    if not row:
        return {
            "template_v1": 0,
            "hybrid_v2": 0,
            "v2_pending": 0,
            "v2_approved": 0,
            "v2_rejected": 0,
            "predictions_with_v2": 0,
            "paired": 0,
        }

    paired = 0
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM prediction_feedback v1
            JOIN prediction_feedback v2
              ON v2.prediction_id = v1.prediction_id
             AND v2.feedback_version = 'v2'
            WHERE v1.feedback_version = 'v1'
              {"AND v1.cluster_id = %s" if cluster_id else ""}
            """,
            ([cluster_id] if cluster_id else []),
        )
        paired_row = cur.fetchone()
        paired = int(paired_row[0] or 0) if paired_row else 0

    return {
        "template_v1": int(row[0] or 0),
        "hybrid_v2": int(row[1] or 0),
        "v2_pending": int(row[2] or 0),
        "v2_approved": int(row[3] or 0),
        "v2_rejected": int(row[4] or 0),
        "predictions_with_v2": int(row[5] or 0),
        "paired": paired,
    }


def list_template_hybrid_pairs(
    conn: psycopg.Connection,
    *,
    cluster_id: Optional[str] = None,
    limit: int = 30,
) -> list[tuple[FeedbackRecord, FeedbackRecord]]:
    """Predictions that have both a Phase B (v1) and Phase G (v2) lesson row."""
    params: list = []
    cluster_clause = ""
    if cluster_id:
        cluster_clause = "AND v1.cluster_id = %s"
        params.append(cluster_id)
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                v1.feedback_id, v1.prediction_id, v1.cluster_id, v1.feedback_json,
                v1.feedback_version, v1.generated_at, v1.generation_method,
                v1.generation_latency_ms, v1.input_tokens, v1.output_tokens, v1.cost_usd,
                v1.feedback_review_status, v1.reviewed_at, v1.reviewed_by,
                v2.feedback_id, v2.prediction_id, v2.cluster_id, v2.feedback_json,
                v2.feedback_version, v2.generated_at, v2.generation_method,
                v2.generation_latency_ms, v2.input_tokens, v2.output_tokens, v2.cost_usd,
                v2.feedback_review_status, v2.reviewed_at, v2.reviewed_by
            FROM prediction_feedback v1
            JOIN prediction_feedback v2
              ON v2.prediction_id = v1.prediction_id
             AND v2.feedback_version = 'v2'
            WHERE v1.feedback_version = 'v1'
              {cluster_clause}
            ORDER BY COALESCE(v2.generated_at, v1.generated_at) DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    pairs: list[tuple[FeedbackRecord, FeedbackRecord]] = []
    for row in rows:
        template = _row_to_feedback_record(row[:14])
        hybrid = _row_to_feedback_record(row[14:28])
        pairs.append((template, hybrid))
    return pairs


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
        generation_latency_ms=float(row[7] or 0) if len(row) > 7 else 0.0,
        input_tokens=int(row[8] or 0) if len(row) > 8 else 0,
        output_tokens=int(row[9] or 0) if len(row) > 9 else 0,
        cost_usd=float(row[10] or 0) if len(row) > 10 else 0.0,
        feedback_review_status=row[11] if len(row) > 11 and row[11] else "approved",
        reviewed_at=row[12] if len(row) > 12 else None,
        reviewed_by=row[13] if len(row) > 13 else None,
    )


def _optional_round(value, *, digits: int = 2) -> Optional[float]:
    return round(float(value), digits) if value is not None else None
