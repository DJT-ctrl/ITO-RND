"""Postgres reads/writes for feedback / calibration / clusters."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Sequence
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
    FeedbackReviewStatus,
    GenerationMethod,
)

logger = logging.getLogger(__name__)


_FEEDBACK_SELECT = """
    feedback_id, prediction_id, cluster_id, feedback_json,
    feedback_version, generated_at, generation_method,
    generation_latency_ms, input_tokens, output_tokens, cost_usd,
    feedback_review_status, reviewed_at, reviewed_by
"""


def fetch_calibration_stats(
    conn: psycopg.Connection,
    *,
    age_aware_enabled: bool = False,
) -> CalibrationStats:
    """Return global signed mean prediction_delta and validated count.

    prediction_delta = actual_percentile − predicted_percentile.
    Empty validated set → n_validated=0, mean_delta=0.0.
    When age_aware_enabled, excludes forced_early rows from the average.
    """
    from validation_pipeline.age_aware import age_aware_learning_sql

    age_clause, age_params = age_aware_learning_sql(
        enabled=age_aware_enabled, alias="predictions"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS n_validated,
                AVG(prediction_delta) AS mean_delta
            FROM predictions
            WHERE status = 'validated'
              AND prediction_delta IS NOT NULL
              {age_clause}
            """,
            tuple(age_params),
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
    age_aware_enabled: bool = False,
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

    global_stats = fetch_calibration_stats(
        conn, age_aware_enabled=age_aware_enabled
    )
    if cluster_id:
        return CalibrationStats(
            n_validated=global_stats.n_validated,
            mean_delta=global_stats.mean_delta,
            cluster_id=cluster_id,
            source=global_stats.source if global_stats.n_validated else "none",
        )
    return global_stats


def refresh_cluster_stats(
    conn: psycopg.Connection,
    *,
    age_aware_enabled: bool = False,
) -> int:
    """Recompute prediction_clusters sample stats from validated feedback rows.

    Preserves existing centroid_embedding when present.
    Returns number of clusters upserted.
    """
    from validation_pipeline.age_aware import age_aware_learning_sql

    age_clause, age_params = age_aware_learning_sql(
        enabled=age_aware_enabled, alias="p"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
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
              {age_clause}
            GROUP BY f.cluster_id
            """,
            tuple(age_params),
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
    # Keep injection roll-ups in sync with stats (template, no LLM).
    try:
        from feedback.summarize import refresh_cluster_rollups

        refresh_cluster_rollups(conn)
    except Exception:
        logger.exception("Cluster roll-up refresh after stats failed")
    return len(rows)


def upsert_prediction_feedback(
    conn: psycopg.Connection,
    payload: FeedbackPayload,
    *,
    feedback_version: str = FEEDBACK_VERSION,
    generation_method: GenerationMethod = "template",
    cluster_id: Optional[str] = None,
    generation_latency_ms: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    feedback_review_status: FeedbackReviewStatus = "approved",
    reviewed_by: Optional[str] = None,
) -> FeedbackRecord:
    """Insert or replace feedback for (prediction_id, feedback_version)."""
    cluster = cluster_id if cluster_id is not None else payload.cluster_id
    payload_dict = payload.model_dump(mode="json")
    reviewer = reviewed_by
    reviewed_at = None
    if feedback_review_status == "approved" and reviewer:
        reviewed_at = datetime.now(timezone.utc)
    elif feedback_review_status == "pending":
        reviewer = None
        reviewed_at = None
    sql = f"""
        INSERT INTO prediction_feedback (
            prediction_id, cluster_id, feedback_json, feedback_version, generation_method,
            generation_latency_ms, input_tokens, output_tokens, cost_usd,
            feedback_review_status, reviewed_at, reviewed_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (prediction_id, feedback_version) DO UPDATE SET
            cluster_id = EXCLUDED.cluster_id,
            feedback_json = EXCLUDED.feedback_json,
            generation_method = EXCLUDED.generation_method,
            generation_latency_ms = EXCLUDED.generation_latency_ms,
            input_tokens = EXCLUDED.input_tokens,
            output_tokens = EXCLUDED.output_tokens,
            cost_usd = EXCLUDED.cost_usd,
            feedback_review_status = EXCLUDED.feedback_review_status,
            reviewed_at = CASE
                WHEN EXCLUDED.feedback_review_status = 'pending' THEN NULL
                WHEN EXCLUDED.reviewed_by IS NOT NULL THEN EXCLUDED.reviewed_at
                ELSE prediction_feedback.reviewed_at
            END,
            reviewed_by = CASE
                WHEN EXCLUDED.feedback_review_status = 'pending' THEN NULL
                WHEN EXCLUDED.reviewed_by IS NOT NULL THEN EXCLUDED.reviewed_by
                ELSE prediction_feedback.reviewed_by
            END,
            generated_at = now()
        RETURNING {_FEEDBACK_SELECT}
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
                max(0.0, generation_latency_ms),
                max(0, input_tokens),
                max(0, output_tokens),
                max(0.0, cost_usd),
                feedback_review_status,
                reviewed_at,
                reviewer,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        raise RuntimeError("upsert_prediction_feedback returned no row")
    return _row_to_feedback_record(row)


def set_feedback_review_status(
    conn: psycopg.Connection,
    feedback_id: UUID,
    status: FeedbackReviewStatus,
    *,
    reviewed_by: str = "dashboard",
) -> Optional[FeedbackRecord]:
    """Approve or reject one feedback row."""
    if status not in {"approved", "rejected", "pending"}:
        raise ValueError(f"Invalid review status: {status}")
    reviewed_at = datetime.now(timezone.utc) if status != "pending" else None
    reviewed_by_value = reviewed_by if status != "pending" else None
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE prediction_feedback
            SET feedback_review_status = %s,
                reviewed_at = %s,
                reviewed_by = %s
            WHERE feedback_id = %s
            RETURNING {_FEEDBACK_SELECT}
            """,
            (status, reviewed_at, reviewed_by_value, feedback_id),
        )
        row = cur.fetchone()
    conn.commit()
    return _row_to_feedback_record(row) if row else None


def count_llm_feedback_generated_today(conn: psycopg.Connection) -> int:
    """Count hybrid/llm feedback rows generated since UTC midnight."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM prediction_feedback
            WHERE generation_method IN ('hybrid', 'llm')
              AND generated_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
            """
        )
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def count_auto_approved_feedback_today(conn: psycopg.Connection) -> int:
    """Count hybrid rows auto-approved since UTC midnight."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM prediction_feedback
            WHERE generation_method = 'hybrid'
              AND feedback_review_status = 'approved'
              AND reviewed_by = 'auto_approve'
              AND reviewed_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
            """
        )
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def list_pending_feedback_for_review(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
) -> list[FeedbackRecord]:
    """Pending v2/hybrid rows sorted by absolute prediction delta desc."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                f.feedback_id, f.prediction_id, f.cluster_id, f.feedback_json,
                f.feedback_version, f.generated_at, f.generation_method,
                f.generation_latency_ms, f.input_tokens, f.output_tokens, f.cost_usd,
                f.feedback_review_status, f.reviewed_at, f.reviewed_by
            FROM prediction_feedback f
            JOIN predictions p ON p.prediction_id = f.prediction_id
            WHERE f.feedback_review_status = 'pending'
            ORDER BY ABS(COALESCE(p.prediction_delta, 0)) DESC, f.generated_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [_row_to_feedback_record(row) for row in rows]


def fetch_cluster_centroids(
    conn: psycopg.Connection,
) -> list[tuple[str, list[float]]]:
    """Return (cluster_id, centroid vector) for clusters that have centroids."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, centroid_embedding
            FROM prediction_clusters
            WHERE centroid_embedding IS NOT NULL
            """
        )
        rows = cur.fetchall()
    results: list[tuple[str, list[float]]] = []
    for cluster_id, embedding in rows:
        if embedding is None:
            continue
        vector = list(embedding) if not isinstance(embedding, list) else embedding
        results.append((cluster_id, [float(x) for x in vector]))
    return results


def upsert_cluster_centroid(
    conn: psycopg.Connection,
    cluster_id: str,
    centroid: Sequence[float],
    *,
    sample_count: Optional[int] = None,
) -> None:
    label = cluster_label(cluster_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prediction_clusters (
                cluster_id, label, sample_count, centroid_embedding, updated_at
            ) VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (cluster_id) DO UPDATE SET
                label = COALESCE(prediction_clusters.label, EXCLUDED.label),
                sample_count = COALESCE(EXCLUDED.sample_count, prediction_clusters.sample_count),
                centroid_embedding = EXCLUDED.centroid_embedding,
                updated_at = now()
            """,
            (
                cluster_id,
                label,
                sample_count if sample_count is not None else 0,
                list(centroid),
            ),
        )
    conn.commit()


def fetch_validated_embeddings_by_metadata_cluster(
    conn: psycopg.Connection,
) -> dict[str, list[list[float]]]:
    """Group validated prediction embeddings by metadata cluster_id from feedback."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COALESCE(f.cluster_id, 'unknown') AS cluster_id,
                p.embedding
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            WHERE p.status = 'validated'
              AND p.embedding IS NOT NULL
            """,
            (FEEDBACK_VERSION,),
        )
        rows = cur.fetchall()
    grouped: dict[str, list[list[float]]] = {}
    for cluster_id, embedding in rows:
        if embedding is None:
            continue
        vector = [float(x) for x in (list(embedding) if not isinstance(embedding, list) else embedding)]
        grouped.setdefault(str(cluster_id), []).append(vector)
    return grouped


def fetch_predictions_missing_embeddings(
    conn: psycopg.Connection,
    *,
    limit: int = 100,
) -> list[tuple[UUID, str]]:
    """Validated predictions with usable content and NULL embedding."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT prediction_id, content
            FROM predictions
            WHERE status = 'validated'
              AND embedding IS NULL
              AND content IS NOT NULL
              AND BTRIM(content) <> ''
            ORDER BY validated_at ASC NULLS LAST, created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [(row[0], str(row[1] or "")) for row in rows]


def update_prediction_embedding(
    conn: psycopg.Connection,
    prediction_id: UUID,
    embedding: Sequence[float],
    *,
    embedding_model_version: str,
) -> None:
    """Persist a backfilled embedding on a prediction row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE predictions
            SET embedding = %s,
                embedding_model_version = %s
            WHERE prediction_id = %s
            """,
            (list(embedding), embedding_model_version, prediction_id),
        )
    conn.commit()


def fetch_feedback_for_prediction(
    conn: psycopg.Connection,
    prediction_id: UUID,
    *,
    feedback_version: str = FEEDBACK_VERSION,
) -> Optional[FeedbackRecord]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_FEEDBACK_SELECT}
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
    age_aware_enabled: bool = False,
) -> list[UUID]:
    """Validated predictions that do not yet have feedback for this version."""
    from validation_pipeline.age_aware import age_aware_learning_sql

    age_clause, age_params = age_aware_learning_sql(
        enabled=age_aware_enabled, alias="p"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.prediction_id
            FROM predictions p
            LEFT JOIN prediction_feedback f
              ON f.prediction_id = p.prediction_id
             AND f.feedback_version = %s
            WHERE p.status = 'validated'
              AND p.prediction_delta IS NOT NULL
              AND p.actual_engagement_percentile IS NOT NULL
              AND f.feedback_id IS NULL
              {age_clause}
            ORDER BY p.validated_at ASC NULLS LAST
            LIMIT %s
            """,
            (feedback_version, *age_params, limit),
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]


# Re-export dashboard read helpers (implementation in dashboard_queries.py).
from feedback.dashboard_queries import (  # noqa: E402
    count_feedback_coverage,
    hybrid_feedback_cost_stats,
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
        generation_latency_ms=float(row[7] or 0) if len(row) > 7 else 0.0,
        input_tokens=int(row[8] or 0) if len(row) > 8 else 0,
        output_tokens=int(row[9] or 0) if len(row) > 9 else 0,
        cost_usd=float(row[10] or 0) if len(row) > 10 else 0.0,
        feedback_review_status=row[11] if len(row) > 11 and row[11] else "approved",
        reviewed_at=row[12] if len(row) > 12 else None,
        reviewed_by=row[13] if len(row) > 13 else None,
    )
