"""Retrieve and format validated feedback for predict-time injection (Phase D)."""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

import psycopg

from feedback.generate import FEEDBACK_VERSION
from feedback.schemas import FeedbackRecord
from feedback.store import _row_to_feedback_record


DEFAULT_FEEDBACK_LIMIT = 5


def fetch_cluster_feedback(
    conn: psycopg.Connection,
    cluster_id: str,
    *,
    limit: int = DEFAULT_FEEDBACK_LIMIT,
    exclude_prediction_id: Optional[UUID] = None,
    feedback_version: str = FEEDBACK_VERSION,
) -> list[FeedbackRecord]:
    """Return recent feedback rows for a cluster (newest first).

    Excludes ``exclude_prediction_id`` to avoid eval leakage when scoring
    a post that already has feedback.
    """
    if not cluster_id or limit <= 0:
        return []

    params: list = [cluster_id, feedback_version]
    exclude_clause = ""
    if exclude_prediction_id is not None:
        exclude_clause = "AND f.prediction_id <> %s"
        params.append(exclude_prediction_id)
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT f.feedback_id, f.prediction_id, f.cluster_id, f.feedback_json,
                   f.feedback_version, f.generated_at, f.generation_method,
                   f.generation_latency_ms, f.input_tokens, f.output_tokens, f.cost_usd
            FROM prediction_feedback f
            WHERE f.cluster_id = %s
              AND f.feedback_version = %s
              {exclude_clause}
            ORDER BY f.generated_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_row_to_feedback_record(row) for row in rows]


def format_feedback_context_block(
    records: Sequence[FeedbackRecord],
    *,
    cluster_id: Optional[str] = None,
) -> str:
    """Compact prompt block for the Predictor Agent. Empty if no records."""
    if not records:
        return ""

    header = "Validated feedback from similar posts"
    if cluster_id:
        header += f" (cluster `{cluster_id}`)"
    header += ":"

    lines = [header]
    for index, record in enumerate(records, start=1):
        payload = record.feedback_json
        delta = payload.delta_summary
        lines.append(
            f"{index}. Direction: {delta.direction}; "
            f"predicted {delta.predicted_percentile:.1f} → actual {delta.actual_percentile:.1f} "
            f"(delta {delta.prediction_delta:+.1f})."
        )
        for lesson in payload.lessons_for_similar_posts[:2]:
            lines.append(f"   Lesson: {lesson}")
        for miss in payload.what_missed[:2]:
            lines.append(f"   Miss: {miss}")
        for worked in payload.what_worked[:1]:
            lines.append(f"   Worked: {worked}")

    lines.append(
        "Use these lessons only as comparative context. "
        "Do not change the deterministic percentile numbers required below."
    )
    return "\n".join(lines)
