"""Clear validation-pipeline and feedback-loop rows for a fresh start."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from config.settings import Settings
from storage.vector_store import create_schema, get_connection


@dataclass(frozen=True)
class ValidationResetResult:
    """Counts of rows removed from each validation/feedback table."""

    prediction_feedback: int = 0
    prediction_engagement_snapshots: int = 0
    predictions: int = 0
    prediction_clusters: int = 0


_RESET_SQL = (
    ("prediction_feedback", "DELETE FROM prediction_feedback"),
    ("prediction_engagement_snapshots", "DELETE FROM prediction_engagement_snapshots"),
    ("predictions", "DELETE FROM predictions"),
    ("prediction_clusters", "DELETE FROM prediction_clusters"),
)


def reset_validation_data(conn: psycopg.Connection) -> ValidationResetResult:
    """Delete all validation and feedback-loop rows (child tables first)."""
    create_schema(conn)
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table, sql in _RESET_SQL:
            cur.execute(sql)
            counts[table] = cur.rowcount
    conn.commit()
    return ValidationResetResult(
        prediction_feedback=counts["prediction_feedback"],
        prediction_engagement_snapshots=counts["prediction_engagement_snapshots"],
        predictions=counts["predictions"],
        prediction_clusters=counts["prediction_clusters"],
    )


def reset_validation_data_for_settings(settings: Settings) -> ValidationResetResult:
    """Open a connection and wipe validation/feedback tables."""
    conn = get_connection(settings)
    try:
        return reset_validation_data(conn)
    finally:
        conn.close()
