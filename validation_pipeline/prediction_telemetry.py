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
) -> PredictionTelemetry:
    """Normalize optional neighbor metadata into a stable persisted schema."""
    neighbor = neighbor_prediction or {}
    raw = neighbor.get("raw_percentile", neighbor.get("percentile"))
    calibrated = neighbor.get("calibrated_percentile", neighbor.get("percentile"))
    source = neighbor.get("calibration_source") or "none"
    if source not in {"cluster", "global", "none"}:
        source = "none"

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
    )


def _optional_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None
