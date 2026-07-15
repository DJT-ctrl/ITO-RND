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
    # Scaffold arms: same numeric scores as with_feedback until Phase J unlocks
    # injectability. Prefer v1 vs approved v2 lesson selection for future compare.
    "raw_with_feedback_v1",
    "raw_with_feedback_v2",
    "calibrated_with_feedback_v1",
    "calibrated_with_feedback_v2",
]


class ReplayRow(BaseModel):
    prediction_id: UUID
    actual_percentile: float
    raw_percentile: float
    cluster_id: Optional[str] = None
    has_approved_v2: bool = False
    # Phase J: optional telemetry for shadow vs live compare when present
    live_percentile: Optional[float] = None
    shadow_percentile: Optional[float] = None
    llm_percentile: Optional[float] = None


class ArmMetrics(BaseModel):
    arm: ArmName
    calibration_enabled: bool
    feedback_injection_enabled: bool
    sample_count: int
    mae: float
    pct_within_10: float
    per_cluster_mae: dict[str, float] = Field(default_factory=dict)
    preferred_feedback_version: Optional[str] = None


class ShadowLiveComparison(BaseModel):
    """Holdout MAE for live vs shadow percentiles when Phase J telemetry exists."""

    sample_count: int = 0
    live_mae: Optional[float] = None
    shadow_mae: Optional[float] = None
    mae_delta: Optional[float] = None


class FeedbackVersionPreference(BaseModel):
    """How many holdout rows would prefer approved v2 vs v1 at retrieve time."""

    holdout_rows: int = 0
    holdout_with_approved_v2: int = 0
    holdout_v1_only: int = 0
    preferred_v2_share_pct: float = 0.0


class FeedbackEvaluationReport(BaseModel):
    schema_version: str = "1.2"
    generated_at: datetime
    total_rows: int
    training_rows: int
    holdout_rows: int
    global_mean_delta: float
    global_calibration_ready: bool
    arms: list[ArmMetrics]
    version_preference: FeedbackVersionPreference = Field(
        default_factory=FeedbackVersionPreference
    )
    shadow_live: ShadowLiveComparison = Field(default_factory=ShadowLiveComparison)
    notes: list[str] = Field(default_factory=list)


# Phase F offline go/no-go gates (see current md/11_GO_NO_GO.md).
CALIBRATION_LIFT_GATE_PCT = 5.0


class PhaseFDecision(BaseModel):
    """Derived Phase F ship decision from an offline evaluation report."""

    calibration_lift_pct: Optional[float] = None
    calibration_gate_met: bool = False
    calibration_decision: Literal["GO", "NO-GO"] = "NO-GO"
    shadow_sample_count: int = 0
    shadow_mae_delta: Optional[float] = None
    shadow_beats_live: bool = False
    injection_decision: Literal["GO", "NO-GO"] = "NO-GO"
    soft_blend_decision: Literal["GO", "NO-GO"] = "NO-GO"


def arm_mae(report: FeedbackEvaluationReport, arm_name: str) -> Optional[float]:
    """Return MAE for a named arm, or None if missing."""
    for arm in report.arms:
        if arm.arm == arm_name:
            return arm.mae
    return None


def calibration_mae_lift_pct(report: FeedbackEvaluationReport) -> Optional[float]:
    """Raw → calibrated MAE improvement % on holdout (primary Phase F gate)."""
    raw = arm_mae(report, "raw_no_feedback")
    calibrated = arm_mae(report, "calibrated_no_feedback")
    if raw is None or calibrated is None or raw <= 0:
        return None
    return round((raw - calibrated) / raw * 100, 2)


def phase_f_decision(report: FeedbackEvaluationReport) -> PhaseFDecision:
    """Map an eval report onto calibration / injection / soft_blend decisions."""
    lift = calibration_mae_lift_pct(report)
    cal_gate = lift is not None and lift >= CALIBRATION_LIFT_GATE_PCT
    shadow = report.shadow_live
    delta = shadow.mae_delta
    # mae_delta = live_mae − shadow_mae; positive means shadow is better.
    shadow_beats = (
        shadow.sample_count > 0
        and delta is not None
        and delta > 0
    )
    return PhaseFDecision(
        calibration_lift_pct=lift,
        calibration_gate_met=cal_gate,
        calibration_decision="GO" if cal_gate else "NO-GO",
        shadow_sample_count=shadow.sample_count,
        shadow_mae_delta=delta,
        shadow_beats_live=shadow_beats,
        injection_decision="GO" if shadow_beats else "NO-GO",
        soft_blend_decision="GO" if shadow_beats else "NO-GO",
    )


def run_offline_replay(
    rows: Sequence[ReplayRow],
    *,
    holdout_size: int = 30,
    global_n_min: int = 30,
    cluster_n_min: int = 50,
) -> FeedbackEvaluationReport:
    """Evaluate calibration × injection arms using stats from non-holdout rows.

    Primary four arms match live flags. Scaffold D-v1 / D-v2 arms reuse the same
    numeric scores (deterministic overwrite) but tag preferred_feedback_version
    so reports document retrieve preference until Phase J.
    """
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
    with_v2 = sum(1 for row in holdout if row.has_approved_v2)
    version_preference = FeedbackVersionPreference(
        holdout_rows=len(holdout),
        holdout_with_approved_v2=with_v2,
        holdout_v1_only=len(holdout) - with_v2,
        preferred_v2_share_pct=round(with_v2 / len(holdout) * 100, 2)
        if holdout
        else 0.0,
    )
    shadow_live = compute_shadow_live_comparison(holdout)
    # When shadow telemetry exists, use shadow scores for with_feedback arms so
    # injection can diverge numerically after Phase J predicts accumulate.
    shadow_scores = [
        row.shadow_percentile
        if row.shadow_percentile is not None
        else row.raw_percentile
        for row in holdout
    ]
    calibrated_shadow_scores = [
        _calibrated_score(
            row.model_copy(
                update={
                    "raw_percentile": (
                        row.shadow_percentile
                        if row.shadow_percentile is not None
                        else row.raw_percentile
                    )
                }
            ),
            global_delta=global_delta,
            global_ready=global_ready,
            cluster_deltas=cluster_deltas,
            cluster_n_min=cluster_n_min,
        )
        if row.shadow_percentile is not None
        else calibrated_scores[i]
        for i, row in enumerate(holdout)
    ]
    has_shadow = shadow_live.sample_count > 0
    arms = [
        _metrics("raw_no_feedback", holdout, raw_scores, False, False),
        _metrics(
            "raw_with_feedback",
            holdout,
            shadow_scores if has_shadow else raw_scores,
            False,
            True,
        ),
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
            calibrated_shadow_scores if has_shadow else calibrated_scores,
            True,
            True,
        ),
        # D-v1 / D-v2 scaffolds — prefer shadow when present (Phase J)
        _metrics(
            "raw_with_feedback_v1",
            holdout,
            shadow_scores if has_shadow else raw_scores,
            False,
            True,
            preferred_feedback_version="v1",
        ),
        _metrics(
            "raw_with_feedback_v2",
            holdout,
            shadow_scores if has_shadow else raw_scores,
            False,
            True,
            preferred_feedback_version="v2",
        ),
        _metrics(
            "calibrated_with_feedback_v1",
            holdout,
            calibrated_shadow_scores if has_shadow else calibrated_scores,
            True,
            True,
            preferred_feedback_version="v1",
        ),
        _metrics(
            "calibrated_with_feedback_v2",
            holdout,
            calibrated_shadow_scores if has_shadow else calibrated_scores,
            True,
            True,
            preferred_feedback_version="v2",
        ),
    ]
    notes = [
        "Holdout rows are excluded from all calibration statistics.",
        (
            f"Holdout approved-v2 availability: {with_v2}/{len(holdout)} "
            f"({version_preference.preferred_v2_share_pct}%)."
        ),
    ]
    if has_shadow:
        notes.append(
            f"Phase J shadow telemetry on {shadow_live.sample_count}/{len(holdout)} "
            f"holdout rows: live_mae={shadow_live.live_mae} "
            f"shadow_mae={shadow_live.shadow_mae} "
            f"delta={shadow_live.mae_delta}."
        )
        notes.append(
            "Injection arms use shadow_percentile when present so MAE can diverge "
            "from non-injection arms after Phase J."
        )
    else:
        notes.append(
            "Feedback-injection arms match non-injection scores until Phase J "
            "shadow_percentile accumulates on validated predictions "
            "(hard_lock still prevents lesson text from changing live scores)."
        )
        notes.append(
            "Scaffold arms raw/calibrated_with_feedback_v1|v2 tag preferred "
            "lesson version; enable shadow_mode or soft_blend to unlock numeric lift."
        )
    return FeedbackEvaluationReport(
        generated_at=datetime.now(timezone.utc),
        total_rows=len(rows),
        training_rows=len(training),
        holdout_rows=len(holdout),
        global_mean_delta=round(global_delta, 4),
        global_calibration_ready=global_ready,
        arms=arms,
        version_preference=version_preference,
        shadow_live=shadow_live,
        notes=notes,
    )


def compute_shadow_live_comparison(
    rows: Sequence[ReplayRow],
) -> ShadowLiveComparison:
    """MAE for live vs shadow percentiles on rows that have both scores."""
    paired = [
        row
        for row in rows
        if row.shadow_percentile is not None
        and (row.live_percentile is not None or row.raw_percentile is not None)
    ]
    if not paired:
        return ShadowLiveComparison()
    live_errors = [
        abs(
            row.actual_percentile
            - float(
                row.live_percentile
                if row.live_percentile is not None
                else row.raw_percentile
            )
        )
        for row in paired
    ]
    shadow_errors = [
        abs(row.actual_percentile - float(row.shadow_percentile)) for row in paired
    ]
    live_mae = round(mean(live_errors), 4)
    shadow_mae = round(mean(shadow_errors), 4)
    return ShadowLiveComparison(
        sample_count=len(paired),
        live_mae=live_mae,
        shadow_mae=shadow_mae,
        mae_delta=round(live_mae - shadow_mae, 4),
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
    *,
    preferred_feedback_version: Optional[str] = None,
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
        preferred_feedback_version=preferred_feedback_version,
    )
