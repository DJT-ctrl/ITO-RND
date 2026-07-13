"""Leakage-safe offline replay for calibration × injection experiment arms."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Literal, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, Field

ArmName = Literal[
    "raw_no_feedback",
    "raw_with_feedback",
    "calibrated_no_feedback",
    "calibrated_with_feedback",
]


class ReplayRow(BaseModel):
    prediction_id: UUID
    actual_percentile: float
    raw_percentile: float
    cluster_id: Optional[str] = None


class ArmMetrics(BaseModel):
    arm: ArmName
    calibration_enabled: bool
    feedback_injection_enabled: bool
    sample_count: int
    mae: float
    pct_within_10: float
    per_cluster_mae: dict[str, float] = Field(default_factory=dict)


class FeedbackEvaluationReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime
    total_rows: int
    training_rows: int
    holdout_rows: int
    global_mean_delta: float
    global_calibration_ready: bool
    arms: list[ArmMetrics]
    notes: list[str] = Field(default_factory=list)


def run_offline_replay(
    rows: Sequence[ReplayRow],
    *,
    holdout_size: int = 30,
    global_n_min: int = 30,
    cluster_n_min: int = 50,
) -> FeedbackEvaluationReport:
    """Evaluate four arms using stats learned only from non-holdout rows."""
    if holdout_size < 1:
        raise ValueError("holdout_size must be at least 1")
    if len(rows) <= holdout_size:
        raise ValueError(
            f"Need more than {holdout_size} validated rows; found {len(rows)}"
        )

    ordered = sorted(rows, key=lambda row: _stable_key(row.prediction_id))
    holdout = ordered[:holdout_size]
    training = ordered[holdout_size:]
    global_deltas = [
        row.actual_percentile - row.raw_percentile for row in training
    ]
    global_ready = len(global_deltas) >= global_n_min
    global_delta = mean(global_deltas) if global_deltas else 0.0

    cluster_deltas: dict[str, list[float]] = defaultdict(list)
    for row in training:
        if row.cluster_id:
            cluster_deltas[row.cluster_id].append(
                row.actual_percentile - row.raw_percentile
            )

    raw_scores = [row.raw_percentile for row in holdout]
    calibrated_scores = [
        _calibrated_score(
            row,
            global_delta=global_delta,
            global_ready=global_ready,
            cluster_deltas=cluster_deltas,
            cluster_n_min=cluster_n_min,
        )
        for row in holdout
    ]
    arms = [
        _metrics("raw_no_feedback", holdout, raw_scores, False, False),
        _metrics("raw_with_feedback", holdout, raw_scores, False, True),
        _metrics(
            "calibrated_no_feedback",
            holdout,
            calibrated_scores,
            True,
            False,
        ),
        _metrics(
            "calibrated_with_feedback",
            holdout,
            calibrated_scores,
            True,
            True,
        ),
    ]
    return FeedbackEvaluationReport(
        generated_at=datetime.now(timezone.utc),
        total_rows=len(rows),
        training_rows=len(training),
        holdout_rows=len(holdout),
        global_mean_delta=round(global_delta, 4),
        global_calibration_ready=global_ready,
        arms=arms,
        notes=[
            "Holdout rows are excluded from all calibration statistics.",
            (
                "Feedback-injection arms have identical numeric scores to their "
                "non-injection counterparts: deterministic predictor post-processing "
                "currently prevents lesson text from changing the percentile."
            ),
        ],
    )


def _stable_key(prediction_id: UUID) -> str:
    return hashlib.sha256(str(prediction_id).encode("utf-8")).hexdigest()


def _calibrated_score(
    row: ReplayRow,
    *,
    global_delta: float,
    global_ready: bool,
    cluster_deltas: dict[str, list[float]],
    cluster_n_min: int,
) -> float:
    deltas = cluster_deltas.get(row.cluster_id or "", [])
    if len(deltas) >= cluster_n_min:
        offset = mean(deltas)
    elif global_ready:
        offset = global_delta
    else:
        offset = 0.0
    return min(100.0, max(0.0, row.raw_percentile + offset))


def _metrics(
    arm: ArmName,
    rows: Sequence[ReplayRow],
    scores: Sequence[float],
    calibration_enabled: bool,
    feedback_injection_enabled: bool,
) -> ArmMetrics:
    errors = [
        abs(row.actual_percentile - score)
        for row, score in zip(rows, scores)
    ]
    cluster_errors: dict[str, list[float]] = defaultdict(list)
    for row, error in zip(rows, errors):
        cluster_errors[row.cluster_id or "unknown"].append(error)
    return ArmMetrics(
        arm=arm,
        calibration_enabled=calibration_enabled,
        feedback_injection_enabled=feedback_injection_enabled,
        sample_count=len(errors),
        mae=round(mean(errors), 4),
        pct_within_10=round(
            sum(error <= 10 for error in errors) / len(errors) * 100,
            2,
        ),
        per_cluster_mae={
            cluster_id: round(mean(values), 4)
            for cluster_id, values in sorted(cluster_errors.items())
        },
    )
