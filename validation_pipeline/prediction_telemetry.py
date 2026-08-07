"""Build durable telemetry for one validation-pipeline prediction."""

from __future__ import annotations

from typing import Any, Optional

from feedback.generate import FEEDBACK_VERSION
from validation_pipeline.schemas import PredictionTelemetry


_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: Optional[str]) -> int:
    """Return a conservative dependency-free prompt token estimate."""
    if not text:
        return 0
    return (len(text) + _CHARS_PER_TOKEN_ESTIMATE - 1) // _CHARS_PER_TOKEN_ESTIMATE


def build_prediction_telemetry(
    neighbor_prediction: dict[str, Any] | None,
    *,
    calibration_enabled: bool,
    feedback_injection_enabled: bool,
    feedback_context: Optional[str],
    feedback_count: int,
    cluster_id: Optional[str],
    injectability: Optional[dict[str, Any]] = None,
    cross_reference_status: Optional[str] = None,
    cross_reference_count: int = 0,
    cross_reference_adjusted_count: int = 0,
) -> PredictionTelemetry:
    """Normalize optional neighbor metadata into a stable persisted schema."""
    neighbor = neighbor_prediction or {}
    raw = neighbor.get("raw_percentile", neighbor.get("percentile"))
    calibrated = neighbor.get("calibrated_percentile", neighbor.get("percentile"))
    source = neighbor.get("calibration_source") or "none"
    if source not in {"cluster", "global", "none"}:
        source = "none"

    inj = injectability or {}
    return PredictionTelemetry(
        raw_percentile=float(raw) if raw is not None else None,
        calibrated_percentile=float(calibrated) if calibrated is not None else None,
        calibration_enabled=calibration_enabled,
        calibration_applied=bool(neighbor.get("calibration_applied", False)),
        calibration_skip_reason=neighbor.get("calibration_skip_reason"),
        mean_delta=_optional_float(neighbor.get("mean_delta")),
        n_validated=_optional_int(neighbor.get("n_validated")),
        calibration_source=source,
        cluster_id=neighbor.get("cluster_id") or cluster_id,
        feedback_injection_enabled=feedback_injection_enabled,
        feedback_injected=bool(feedback_context),
        feedback_count=max(0, int(feedback_count)),
        feedback_version=FEEDBACK_VERSION if feedback_injection_enabled else None,
        feedback_chars=len(feedback_context or ""),
        feedback_token_estimate=estimate_tokens(feedback_context),
        llm_percentile=_optional_float(inj.get("llm_percentile")),
        shadow_percentile=_optional_float(inj.get("shadow_percentile")),
        shadow_calibration_applied=bool(inj.get("shadow_calibration_applied", False)),
        shadow_feedback_count=max(0, int(inj.get("shadow_feedback_count") or 0)),
        injectability_mode=inj.get("injectability_mode"),
        soft_blend_weight=_optional_float(inj.get("soft_blend_weight")),
        target_horizon_hours=_optional_float(inj.get("target_horizon_hours")),
        prediction_lane=inj.get("prediction_lane"),
        age_bucket=inj.get("age_bucket"),
        percentile_source=inj.get("percentile_source"),
        neighbor_age_prefer=(
            bool(inj["neighbor_age_prefer"])
            if inj.get("neighbor_age_prefer") is not None
            else None
        ),
        cross_reference_status=cross_reference_status,
        cross_reference_count=max(0, int(cross_reference_count)),
        cross_reference_adjusted_count=max(0, int(cross_reference_adjusted_count)),
    )


def _optional_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None
