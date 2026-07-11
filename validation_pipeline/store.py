"""Postgres CRUD for predictions and engagement snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg

from validation_pipeline.schemas import (
    AccuracyAggregates,
    EngagementActuals,
    NewPrediction,
    PredictionRecord,
    ValidationScores,
)

_PREDICTION_COLUMNS = [
    "prediction_id",
    "linkedin_post_id",
    "linkedin_url",
    "author_public_id",
    "content",
    "posted_at",
    "predicted_engagement_percentile",
    "predicted_total_engagement",
    "predicted_likes",
    "predicted_comments",
    "predicted_shares",
    "prediction_method",
    "neighbor_count",
    "status",
    "validation_due_at",
    "validated_at",
    "actual_likes",
    "actual_comments",
    "actual_shares",
    "actual_total_engagement",
    "actual_engagement_percentile",
    "prediction_delta",
    "accuracy_score",
    "likes_delta",
    "comments_delta",
    "shares_delta",
    "total_engagement_delta",
    "validation_error",
    "created_at",
]


def _row_to_prediction(row: tuple[Any, ...], columns: list[str]) -> PredictionRecord:
    data = dict(zip(columns, row))
    return PredictionRecord(**data)


def prediction_exists(conn: psycopg.Connection, linkedin_post_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM predictions WHERE linkedin_post_id = %s LIMIT 1",
            (linkedin_post_id,),
        )
        return cur.fetchone() is not None


def insert_prediction(conn: psycopg.Connection, prediction: NewPrediction) -> PredictionRecord:
    sql = """
        INSERT INTO predictions (
            linkedin_post_id, linkedin_url, author_public_id, content, posted_at,
            predicted_engagement_percentile, predicted_total_engagement,
            predicted_likes, predicted_comments, predicted_shares,
            prediction_method, neighbor_count, validation_due_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING prediction_id, created_at
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                prediction.linkedin_post_id,
                prediction.linkedin_url,
                prediction.author_public_id,
                prediction.content,
                prediction.posted_at,
                prediction.predicted_engagement_percentile,
                prediction.predicted_total_engagement,
                prediction.predicted_likes,
                prediction.predicted_comments,
                prediction.predicted_shares,
                prediction.prediction_method,
                prediction.neighbor_count,
                prediction.validation_due_at,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    prediction_id, created_at = row
    return PredictionRecord(
        prediction_id=prediction_id,
        created_at=created_at,
        status="scheduled",
        **prediction.model_dump(),
    )


def fetch_due_predictions(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
    as_of: Optional[datetime] = None,
) -> list[PredictionRecord]:
    as_of = as_of or datetime.now(timezone.utc)
    select_clause = ", ".join(_PREDICTION_COLUMNS)
    sql = f"""
        SELECT {select_clause}
        FROM predictions
        WHERE status = 'scheduled' AND validation_due_at <= %s
        ORDER BY validation_due_at ASC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (as_of, limit))
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [_row_to_prediction(row, columns) for row in rows]


def list_predictions(
    conn: psycopg.Connection,
    *,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[PredictionRecord]:
    select_clause = ", ".join(_PREDICTION_COLUMNS)
    if status:
        sql = f"""
            SELECT {select_clause}
            FROM predictions
            WHERE status = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        params: tuple[Any, ...] = (status, limit)
    else:
        sql = f"""
            SELECT {select_clause}
            FROM predictions
            ORDER BY created_at DESC
            LIMIT %s
        """
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [_row_to_prediction(row, columns) for row in rows]


def mark_validating(conn: psycopg.Connection, prediction_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE predictions SET status = 'validating' WHERE prediction_id = %s",
            (prediction_id,),
        )
    conn.commit()


def mark_validated(
    conn: psycopg.Connection,
    prediction_id: UUID,
    actuals: EngagementActuals,
    scores: ValidationScores,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE predictions SET
                status = 'validated',
                validated_at = %s,
                actual_likes = %s,
                actual_comments = %s,
                actual_shares = %s,
                actual_total_engagement = %s,
                actual_engagement_percentile = %s,
                prediction_delta = %s,
                accuracy_score = %s,
                likes_delta = %s,
                comments_delta = %s,
                shares_delta = %s,
                total_engagement_delta = %s,
                validation_error = NULL
            WHERE prediction_id = %s
            """,
            (
                datetime.now(timezone.utc),
                actuals.likes,
                actuals.comments,
                actuals.shares,
                actuals.total_engagement,
                scores.actual_engagement_percentile,
                scores.prediction_delta,
                scores.accuracy_score,
                scores.likes_delta,
                scores.comments_delta,
                scores.shares_delta,
                scores.total_engagement_delta,
                prediction_id,
            ),
        )
    conn.commit()


def mark_failed(conn: psycopg.Connection, prediction_id: UUID, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE predictions SET
                status = 'failed',
                validated_at = %s,
                validation_error = %s
            WHERE prediction_id = %s
            """,
            (datetime.now(timezone.utc), error[:2000], prediction_id),
        )
    conn.commit()


def insert_snapshot(
    conn: psycopg.Connection,
    prediction_id: UUID,
    actuals: EngagementActuals,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prediction_engagement_snapshots (
                prediction_id, likes, comments, shares, total_engagement
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                prediction_id,
                actuals.likes,
                actuals.comments,
                actuals.shares,
                actuals.total_engagement,
            ),
        )
    conn.commit()


def fetch_accuracy_aggregates(conn: psycopg.Connection) -> AccuracyAggregates:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_validated,
                AVG(ABS(prediction_delta)) AS mae,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(prediction_delta)) AS median_ae,
                AVG(CASE WHEN ABS(prediction_delta) <= 10 THEN 1.0 ELSE 0.0 END) * 100 AS pct_within_10,
                AVG(accuracy_score) AS mean_accuracy,
                AVG(ABS(likes_delta)) AS mae_likes,
                AVG(ABS(comments_delta)) AS mae_comments,
                AVG(ABS(shares_delta)) AS mae_shares,
                AVG(ABS(total_engagement_delta)) AS mae_total,
                AVG(
                    CASE
                        WHEN predicted_total_engagement > 0
                             AND ABS(total_engagement_delta) <= predicted_total_engagement * 0.2
                        THEN 1.0
                        WHEN predicted_total_engagement = 0 AND total_engagement_delta = 0
                        THEN 1.0
                        ELSE 0.0
                    END
                ) * 100 AS pct_total_within_20pct
            FROM predictions
            WHERE status = 'validated'
            """
        )
        summary = cur.fetchone()

        cur.execute(
            """
            SELECT
                DATE_TRUNC('day', validated_at) AS day,
                AVG(ABS(prediction_delta)) AS mae,
                AVG(accuracy_score) AS mean_accuracy,
                COUNT(*) AS count
            FROM predictions
            WHERE status = 'validated' AND validated_at IS NOT NULL
            GROUP BY DATE_TRUNC('day', validated_at)
            ORDER BY day ASC
            """
        )
        time_rows = cur.fetchall()

    total = int(summary[0] or 0)
    if total == 0:
        return AccuracyAggregates()

    time_series = [
        {
            "day": row[0].isoformat() if row[0] else None,
            "mae": round(float(row[1]), 2) if row[1] is not None else None,
            "mean_accuracy": round(float(row[2]), 2) if row[2] is not None else None,
            "count": int(row[3]),
        }
        for row in time_rows
    ]

    return AccuracyAggregates(
        total_validated=total,
        mean_absolute_error=round(float(summary[1]), 2) if summary[1] is not None else None,
        median_absolute_error=round(float(summary[2]), 2) if summary[2] is not None else None,
        pct_within_10=round(float(summary[3]), 1) if summary[3] is not None else None,
        mean_accuracy_score=round(float(summary[4]), 2) if summary[4] is not None else None,
        mae_likes=round(float(summary[5]), 2) if summary[5] is not None else None,
        mae_comments=round(float(summary[6]), 2) if summary[6] is not None else None,
        mae_shares=round(float(summary[7]), 2) if summary[7] is not None else None,
        mae_total_engagement=round(float(summary[8]), 2) if summary[8] is not None else None,
        pct_total_within_20pct=round(float(summary[9]), 1) if summary[9] is not None else None,
        time_series=time_series,
    )
