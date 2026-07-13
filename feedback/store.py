"""Postgres reads/writes for feedback / calibration / clusters."""

from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from feedback.generate import FEEDBACK_VERSION
from feedback.routing import cluster_label
from feedback.schemas import (
    CalibrationStats,
    ClusterStats,
    FeedbackPayload,
    FeedbackRecord,
    GenerationMethod,
)


def fetch_calibration_stats(conn: psycopg.Connection) -> CalibrationStats:
    """Return global signed mean prediction_delta and validated count.

    prediction_delta = actual_percentile − predicted_percentile.
    Empty validated set → n_validated=0, mean_delta=0.0.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS n_validated,
                AVG(prediction_delta) AS mean_delta
            FROM predictions
            WHERE status = 'validated'
              AND prediction_delta IS NOT NULL
            """
        )
        row = cur.fetchone()

    if row is None:
        return CalibrationStats(n_validated=0, mean_delta=0.0, source="none")

    n = int(row[0] or 0)
    if n == 0:
        return CalibrationStats(n_validated=0, mean_delta=0.0, source="none")

    mean_delta = round(float(row[1]), 4) if row[1] is not None else 0.0
    return CalibrationStats(
        n_validated=n,
        mean_delta=mean_delta,
        source="global",
    )


def fetch_cluster_stats(
    conn: psycopg.Connection,
    cluster_id: str,
) -> Optional[ClusterStats]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, label, sample_count, mean_delta, std_delta
            FROM prediction_clusters
            WHERE cluster_id = %s
            """,
            (cluster_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ClusterStats(
        cluster_id=row[0],
        label=row[1],
        sample_count=int(row[2] or 0),
        mean_delta=float(row[3]) if row[3] is not None else None,
        std_delta=float(row[4]) if row[4] is not None else None,
    )


def resolve_calibration_stats(
    conn: psycopg.Connection,
    *,
    cluster_id: Optional[str] = None,
    cluster_n_min: int = 50,
) -> CalibrationStats:
    """Prefer cluster mean_delta when sample_count >= cluster_n_min; else global.

    Fallback chain: cluster → global → none.
    """
    if cluster_id:
        cluster = fetch_cluster_stats(conn, cluster_id)
        if (
            cluster is not None
            and cluster.sample_count >= cluster_n_min
            and cluster.mean_delta is not None
        ):
            return CalibrationStats(
                n_validated=cluster.sample_count,
                mean_delta=round(float(cluster.mean_delta), 4),
                cluster_id=cluster_id,
                source="cluster",
            )

    global_stats = fetch_calibration_stats(conn)
    if cluster_id:
        return CalibrationStats(
            n_validated=global_stats.n_validated,
            mean_delta=global_stats.mean_delta,
            cluster_id=cluster_id,
            source=global_stats.source if global_stats.n_validated else "none",
        )
    return global_stats


def refresh_cluster_stats(conn: psycopg.Connection) -> int:
    """Recompute prediction_clusters from validated feedback rows.

    Returns number of clusters upserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                f.cluster_id,
                COUNT(*)::INTEGER AS sample_count,
                AVG(p.prediction_delta) AS mean_delta,
                STDDEV_SAMP(p.prediction_delta) AS std_delta
            FROM prediction_feedback f
            JOIN predictions p ON p.prediction_id = f.prediction_id
            WHERE f.cluster_id IS NOT NULL
              AND p.status = 'validated'
              AND p.prediction_delta IS NOT NULL
            GROUP BY f.cluster_id
            """
        )
        rows = cur.fetchall()

        upsert = """
            INSERT INTO prediction_clusters (
                cluster_id, label, sample_count, mean_delta, std_delta, updated_at
            ) VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (cluster_id) DO UPDATE SET
                label = COALESCE(prediction_clusters.label, EXCLUDED.label),
                sample_count = EXCLUDED.sample_count,
                mean_delta = EXCLUDED.mean_delta,
                std_delta = EXCLUDED.std_delta,
                updated_at = now()
        """
        for cluster_id, sample_count, mean_delta, std_delta in rows:
            cur.execute(
                upsert,
                (
                    cluster_id,
                    cluster_label(cluster_id),
                    int(sample_count),
                    float(mean_delta) if mean_delta is not None else None,
                    float(std_delta) if std_delta is not None else None,
                ),
            )
    conn.commit()
    return len(rows)


def upsert_prediction_feedback(
    conn: psycopg.Connection,
    payload: FeedbackPayload,
    *,
    feedback_version: str = FEEDBACK_VERSION,
    generation_method: GenerationMethod = "template",
    cluster_id: Optional[str] = None,
) -> FeedbackRecord:
    """Insert or replace feedback for (prediction_id, feedback_version)."""
    cluster = cluster_id if cluster_id is not None else payload.cluster_id
    payload_dict = payload.model_dump(mode="json")
    sql = """
        INSERT INTO prediction_feedback (
            prediction_id, cluster_id, feedback_json, feedback_version, generation_method
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (prediction_id, feedback_version) DO UPDATE SET
            cluster_id = EXCLUDED.cluster_id,
            feedback_json = EXCLUDED.feedback_json,
            generation_method = EXCLUDED.generation_method,
            generated_at = now()
        RETURNING feedback_id, prediction_id, cluster_id, feedback_json,
                  feedback_version, generated_at, generation_method
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                payload.prediction_id,
                cluster,
                Jsonb(payload_dict),
                feedback_version,
                generation_method,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        raise RuntimeError("upsert_prediction_feedback returned no row")
    return _row_to_feedback_record(row)


def fetch_feedback_for_prediction(
    conn: psycopg.Connection,
    prediction_id: UUID,
    *,
    feedback_version: str = FEEDBACK_VERSION,
) -> Optional[FeedbackRecord]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT feedback_id, prediction_id, cluster_id, feedback_json,
                   feedback_version, generated_at, generation_method
            FROM prediction_feedback
            WHERE prediction_id = %s AND feedback_version = %s
            LIMIT 1
            """,
            (prediction_id, feedback_version),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_feedback_record(row)


def fetch_validated_prediction_ids_missing_feedback(
    conn: psycopg.Connection,
    *,
    limit: int = 100,
    feedback_version: str = FEEDBACK_VERSION,
) -> list[UUID]:
    """Validated predictions that do not yet have feedback for this version."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.prediction_id
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            WHERE p.status = 'validated'
              AND p.prediction_delta IS NOT NULL
              AND p.actual_engagement_percentile IS NOT NULL
              AND f.feedback_id IS NULL
            ORDER BY p.validated_at ASC NULLS LAST
            LIMIT %s
            """,
            (feedback_version, limit),
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]


# Re-export dashboard read helpers (implementation in dashboard_queries.py).
from feedback.dashboard_queries import (  # noqa: E402
    count_feedback_coverage,
    list_clusters,
    list_recent_feedback,
)


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
