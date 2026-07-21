"""Retrieve and format validated feedback for predict-time injection (Phase D/H/I)."""

from __future__ import annotations

from typing import Literal, Optional, Sequence
from uuid import UUID

import psycopg

from agents.prompt_safety import wrap_untrusted_text
from feedback.generate import FEEDBACK_VERSION_V2
from feedback.schemas import FeedbackRecord
from feedback.store import _row_to_feedback_record
from feedback.summarize import structured_bias_line


DEFAULT_FEEDBACK_LIMIT = 5
InjectionFormat = Literal["lessons", "rollup_top2", "rollup_contrastive"]
_FEEDBACK_SELECT = """
    f.feedback_id, f.prediction_id, f.cluster_id, f.feedback_json,
    f.feedback_version, f.generated_at, f.generation_method,
    f.generation_latency_ms, f.input_tokens, f.output_tokens, f.cost_usd,
    f.feedback_review_status, f.reviewed_at, f.reviewed_by
"""


def fetch_cluster_feedback(
    conn: psycopg.Connection,
    cluster_id: str,
    *,
    limit: int = DEFAULT_FEEDBACK_LIMIT,
    exclude_prediction_id: Optional[UUID] = None,
    feedback_version: Optional[str] = None,
    approved_only: bool = True,
    query_embedding: Optional[Sequence[float]] = None,
    age_aware_enabled: bool = False,
) -> list[FeedbackRecord]:
    """Return feedback rows for a cluster.

    Prefer v2 over v1 when ``feedback_version`` is None.
    When ``query_embedding`` is set, rank by cosine distance to the lesson
    prediction embedding, then recency. Otherwise newest-first.
    When ``age_aware_enabled``, skip lessons from forced_early validations.
    """
    from validation_pipeline.age_aware import age_aware_learning_sql

    if not cluster_id or limit <= 0:
        return []

    version_clause = ""
    exclude_clause = ""
    approved_clause = "AND f.feedback_review_status = 'approved'" if approved_only else ""
    age_clause, age_params = age_aware_learning_sql(
        enabled=age_aware_enabled, alias="p"
    )

    where_params: list = [cluster_id]
    if feedback_version:
        version_clause = "AND f.feedback_version = %s"
        where_params.append(feedback_version)
    if exclude_prediction_id is not None:
        exclude_clause = "AND f.prediction_id <> %s"
        where_params.append(exclude_prediction_id)
    where_params.extend(age_params)

    if query_embedding:
        select_distance = (
            ", (p.embedding::halfvec(3072) <=> %s::halfvec(3072)) AS distance"
        )
        order_clause = (
            "ORDER BY "
            "CASE WHEN p.embedding IS NULL THEN 1 ELSE 0 END ASC, "
            "distance ASC NULLS LAST, "
            "f.generated_at DESC"
        )
        params = [list(query_embedding), *where_params, limit]
    else:
        select_distance = ""
        order_clause = "ORDER BY f.generated_at DESC"
        params = [*where_params, limit]

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_FEEDBACK_SELECT}{select_distance}
            FROM prediction_feedback f
            LEFT JOIN predictions p ON p.prediction_id = f.prediction_id
            WHERE f.cluster_id = %s
              {version_clause}
              {exclude_clause}
              {approved_clause}
              {age_clause}
            {order_clause}
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    records = [_row_to_feedback_record(row[:14]) for row in rows]
    if feedback_version is None:
        records = _prefer_v2_records(records, limit=limit)
    return records


def _prefer_v2_records(
    records: Sequence[FeedbackRecord],
    *,
    limit: int,
) -> list[FeedbackRecord]:
    """Preserve order; skip v1 when a v2 for the same prediction_id exists."""
    v2_ids = {
        r.prediction_id
        for r in records
        if r.feedback_version == FEEDBACK_VERSION_V2
    }
    chosen: list[FeedbackRecord] = []
    seen: set[UUID] = set()
    for record in records:
        if record.prediction_id in seen:
            continue
        if (
            record.feedback_version != FEEDBACK_VERSION_V2
            and record.prediction_id in v2_ids
        ):
            continue
        chosen.append(record)
        seen.add(record.prediction_id)
        if len(chosen) >= limit:
            break
    return chosen


def select_contrastive_pair(
    records: Sequence[FeedbackRecord],
) -> tuple[Optional[FeedbackRecord], Optional[FeedbackRecord]]:
    """Pick largest |delta| miss and nearest-hit (|delta| smallest) in the set."""
    if not records:
        return None, None
    ranked = sorted(
        records,
        key=lambda r: abs(float(r.feedback_json.delta_summary.prediction_delta)),
        reverse=True,
    )
    miss = ranked[0]
    near = min(
        records,
        key=lambda r: abs(float(r.feedback_json.delta_summary.prediction_delta)),
    )
    if miss.prediction_id == near.prediction_id and len(records) > 1:
        near = ranked[-1]
    if miss.prediction_id == near.prediction_id:
        return miss, None
    return miss, near


def format_feedback_context_block(
    records: Sequence[FeedbackRecord],
    *,
    cluster_id: Optional[str] = None,
    injection_format: InjectionFormat = "lessons",
    rollup_summary: Optional[str] = None,
    mean_delta: Optional[float] = None,
    sample_count: int = 0,
) -> str:
    """Compact prompt block for the Predictor Agent. Empty if nothing to show."""
    fmt: InjectionFormat = injection_format
    if fmt not in {"lessons", "rollup_top2", "rollup_contrastive"}:
        fmt = "lessons"

    if fmt == "lessons":
        return _format_lessons_block(records, cluster_id=cluster_id)

    lines: list[str] = []
    header = "Validated feedback from similar posts"
    if cluster_id:
        header += f" (cluster `{cluster_id}`)"
    header += ":"
    lines.append(header)

    summary = (rollup_summary or "").strip()
    if summary:
        lines.append(f"Cluster roll-up: {summary}")
    lines.append(
        structured_bias_line(mean_delta=mean_delta, sample_count=sample_count)
    )

    if fmt == "rollup_contrastive":
        miss, near = select_contrastive_pair(records)
        if miss is not None:
            lines.append("Contrastive pair:")
            lines.extend(_format_example_lines(miss, label="Big miss"))
            if near is not None:
                lines.extend(_format_example_lines(near, label="Near hit"))
        elif records:
            lines.extend(_format_numbered_lessons(list(records)[:2]))
    else:
        # rollup_top2
        lines.extend(_format_numbered_lessons(list(records)[:2]))

    if len(lines) <= 2 and not records and not summary:
        return ""

    lines.append(
        "Do not change the deterministic percentile or engagement counts from these lessons; "
        "use them only as qualitative context."
    )
    return "\n".join(lines)


def _format_lessons_block(
    records: Sequence[FeedbackRecord],
    *,
    cluster_id: Optional[str] = None,
) -> str:
    if not records:
        return ""

    header = "Validated feedback from similar posts"
    if cluster_id:
        header += f" (cluster `{cluster_id}`)"
    header += ":"

    lines = [header]
    lines.extend(_format_numbered_lessons(records))
    lines.append(
        "Do not change the deterministic percentile or engagement counts from these lessons; "
        "use them only as qualitative context."
    )
    return "\n".join(lines)


def _format_numbered_lessons(records: Sequence[FeedbackRecord]) -> list[str]:
    lines: list[str] = []
    for index, record in enumerate(records, start=1):
        lines.extend(_format_example_lines(record, label=str(index)))
    return lines


def _format_example_lines(record: FeedbackRecord, *, label: str) -> list[str]:
    payload = record.feedback_json
    delta = payload.delta_summary
    lesson_text = "; ".join(payload.lessons_for_similar_posts) or "n/a"
    missed_text = "; ".join(payload.what_missed) or "n/a"
    safe_lesson = wrap_untrusted_text(lesson_text, tag="feedback_lesson")
    safe_missed = wrap_untrusted_text(missed_text, tag="feedback_miss")
    prefix = f"{label}." if label.isdigit() else f"{label}:"
    return [
        f"{prefix} Direction: {delta.direction}; "
        f"predicted {delta.predicted_percentile:.1f} → actual {delta.actual_percentile:.1f} "
        f"(delta {delta.prediction_delta:+.1f}; version {record.feedback_version}).",
        f"   Miss: {safe_missed}",
        f"   Lesson: {safe_lesson}",
    ]


def example_limit_for_format(
    injection_format: str,
    configured_limit: int,
) -> int:
    """How many lesson rows to fetch for the chosen injection format."""
    if injection_format == "rollup_top2":
        return min(2, max(1, configured_limit))
    if injection_format == "rollup_contrastive":
        # Need a wider pool to pick miss vs near-hit.
        return max(configured_limit, 8)
    return max(1, configured_limit)
