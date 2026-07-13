"""Pure calibration math for engagement percentile predictions.

Convention (locked):
  prediction_delta = actual_percentile − predicted_percentile
  calibrated = clamp(raw + mean_delta, 0, 100)

Overestimates produce a negative mean_delta, which pulls the next raw score down.
"""

from __future__ import annotations

from collections.abc import Sequence

from feedback.schemas import CalibrationResult


def compute_mean_delta(deltas: Sequence[float]) -> float:
    """Return the arithmetic mean of signed prediction deltas, or 0.0 if empty."""
    if not deltas:
        return 0.0
    return sum(deltas) / len(deltas)


def _clamp_percentile(value: float) -> float:
    return max(0.0, min(100.0, value))


def apply_calibration(
    raw_percentile: float,
    mean_delta: float,
    n: int,
    n_min: int,
) -> CalibrationResult:
    """Apply mean_delta to raw_percentile when sample size meets n_min.

    Below n_min the raw value is returned unchanged (cold start / thin data).
    """
    raw = float(raw_percentile)
    if n < n_min:
        return CalibrationResult(
            raw_percentile=raw,
            calibrated_percentile=raw,
            mean_delta=float(mean_delta),
            n_validated=n,
            n_min=n_min,
            applied=False,
            skip_reason="below_n_min",
        )

    calibrated = round(_clamp_percentile(raw + float(mean_delta)), 2)
    return CalibrationResult(
        raw_percentile=raw,
        calibrated_percentile=calibrated,
        mean_delta=float(mean_delta),
        n_validated=n,
        n_min=n_min,
        applied=True,
        skip_reason=None,
    )
