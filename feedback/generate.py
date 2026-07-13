"""Template-first structured feedback from validated prediction rows.

Phase B: no LLM. All text is derived from stored deltas and scores.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from feedback.schemas import DeltaSummary, FeedbackDirection, FeedbackPayload
from feedback.routing import assign_cluster_id
from validation_pipeline.schemas import PredictionRecord, ValidationScores

FEEDBACK_VERSION = "v1"
ACCURATE_DELTA_ABS = 5.0


def direction_from_delta(prediction_delta: float) -> FeedbackDirection:
    if abs(prediction_delta) < ACCURATE_DELTA_ABS:
        return "accurate"
    if prediction_delta < 0:
        return "overestimated"
    return "underestimated"


def generate_template_feedback(
    prediction_id: UUID,
    *,
    predicted_percentile: float,
    actual_percentile: float,
    prediction_delta: float,
    accuracy_score: Optional[float] = None,
    prediction_method: Optional[str] = None,
    likes_delta: Optional[float] = None,
    comments_delta: Optional[float] = None,
    shares_delta: Optional[float] = None,
    total_engagement_delta: Optional[float] = None,
    cluster_id: Optional[str] = None,
) -> FeedbackPayload:
    """Build compact, number-grounded feedback JSON (template method)."""
    delta = round(float(prediction_delta), 2)
    predicted = round(float(predicted_percentile), 2)
    actual = round(float(actual_percentile), 2)
    direction = direction_from_delta(delta)

    delta_summary = DeltaSummary(
        predicted_percentile=predicted,
        actual_percentile=actual,
        prediction_delta=delta,
        direction=direction,
    )

    what_worked: list[str] = []
    what_missed: list[str] = []
    lessons: list[str] = []

    if direction == "accurate":
        what_worked.append(
            f"Predicted {predicted:.1f}th percentile; actual {actual:.1f} "
            f"(delta {delta:+.1f}, within ±{ACCURATE_DELTA_ABS:.0f})."
        )
        lessons.append(
            "Similar posts: neighbor-weighted percentile was reliable within ±5 pts."
        )
    elif direction == "overestimated":
        what_missed.append(
            f"Overestimated engagement percentile by {abs(delta):.1f} pts "
            f"(predicted {predicted:.1f}, actual {actual:.1f})."
        )
        lessons.append(
            f"Similar posts: bias toward lower percentiles by ~{abs(delta):.0f} pts "
            "versus neighbor average."
        )
    else:
        what_missed.append(
            f"Underestimated engagement percentile by {delta:.1f} pts "
            f"(predicted {predicted:.1f}, actual {actual:.1f})."
        )
        lessons.append(
            f"Similar posts: bias toward higher percentiles by ~{delta:.0f} pts "
            "versus neighbor average."
        )

    if accuracy_score is not None:
        what_worked.append(f"Accuracy score {float(accuracy_score):.1f}/100.")

    if prediction_method:
        what_worked.append(f"Prediction method: {prediction_method}.")

    metric_notes = _metric_delta_notes(
        likes_delta=likes_delta,
        comments_delta=comments_delta,
        shares_delta=shares_delta,
        total_engagement_delta=total_engagement_delta,
    )
    what_missed.extend(metric_notes)

    return FeedbackPayload(
        prediction_id=prediction_id,
        delta_summary=delta_summary,
        what_worked=what_worked,
        what_missed=what_missed,
        lessons_for_similar_posts=lessons,
        cluster_id=cluster_id,
    )


def generate_template_feedback_from_record(
    record: PredictionRecord,
    *,
    follower_count: Optional[int] = None,
) -> FeedbackPayload:
    """Generate feedback from a validated PredictionRecord."""
    if record.actual_engagement_percentile is None or record.prediction_delta is None:
        raise ValueError(
            f"Prediction {record.prediction_id} is missing actual percentile or delta"
        )
    cluster_id = assign_cluster_id(record.content, follower_count)
    return generate_template_feedback(
        record.prediction_id,
        predicted_percentile=record.predicted_engagement_percentile,
        actual_percentile=record.actual_engagement_percentile,
        prediction_delta=record.prediction_delta,
        accuracy_score=record.accuracy_score,
        prediction_method=record.prediction_method,
        likes_delta=record.likes_delta,
        comments_delta=record.comments_delta,
        shares_delta=record.shares_delta,
        total_engagement_delta=record.total_engagement_delta,
        cluster_id=cluster_id,
    )


def generate_template_feedback_from_scores(
    prediction: PredictionRecord,
    scores: ValidationScores,
    *,
    follower_count: Optional[int] = None,
) -> FeedbackPayload:
    """Generate feedback immediately after scoring (before re-fetch)."""
    cluster_id = assign_cluster_id(prediction.content, follower_count)
    return generate_template_feedback(
        prediction.prediction_id,
        predicted_percentile=prediction.predicted_engagement_percentile,
        actual_percentile=scores.actual_engagement_percentile,
        prediction_delta=scores.prediction_delta,
        accuracy_score=scores.accuracy_score,
        prediction_method=prediction.prediction_method,
        likes_delta=scores.likes_delta,
        comments_delta=scores.comments_delta,
        shares_delta=scores.shares_delta,
        total_engagement_delta=scores.total_engagement_delta,
        cluster_id=cluster_id,
    )


def _metric_delta_notes(
    *,
    likes_delta: Optional[float],
    comments_delta: Optional[float],
    shares_delta: Optional[float],
    total_engagement_delta: Optional[float],
) -> list[str]:
    notes: list[str] = []
    for label, value in (
        ("likes", likes_delta),
        ("comments", comments_delta),
        ("shares", shares_delta),
        ("total engagement", total_engagement_delta),
    ):
        if value is None:
            continue
        if abs(value) < 1:
            continue
        notes.append(f"{label.capitalize()} delta {value:+.0f} vs predicted.")
    return notes
