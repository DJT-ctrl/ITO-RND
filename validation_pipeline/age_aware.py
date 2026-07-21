"""Post-age classification for validation grading and AI learning filters.

Always safe to compute/persist age + mode. When ``VALIDATION_AGE_AWARE_ENABLED``
is on, ``forced_early`` rows are excluded from calibration / feedback injection
so immature engagement does not skew the learning pool.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

ValidationMode = Literal[
    "live_48h",
    "backtest_mature",
    "forced_early",
    "live_out_of_window",
]

# Modes excluded from calibration / feedback learning when age-aware is ON.
LEARNING_EXCLUDED_MODES = frozenset({"forced_early"})


def classify_validation_mode(
    *,
    posted_at: datetime,
    validated_at: datetime,
    horizon_hours: float,
    is_backtest: bool = False,
    tolerance_hours: float = 6.0,
    mature_min_hours: float = 72.0,
) -> tuple[float, ValidationMode]:
    """Return (validation_age_hours, validation_mode).

    - forced_early: live younger than horizon − tolerance, or backtest younger
      than mature_min_hours (default 72h)
    - live_48h: within horizon ± tolerance (canonical live window)
    - backtest_mature: backtest lane and age ≥ mature_min_hours
    - live_out_of_window: live lane but outside the ±tolerance band (usually older)
    """
    age_h = max(0.0, (validated_at - posted_at).total_seconds() / 3600.0)
    age_rounded = round(age_h, 2)
    low = max(0.0, float(horizon_hours) - float(tolerance_hours))
    high = float(horizon_hours) + float(tolerance_hours)

    if is_backtest:
        if age_h < float(mature_min_hours):
            return age_rounded, "forced_early"
        return age_rounded, "backtest_mature"
    if age_h < low:
        return age_rounded, "forced_early"
    if low <= age_h <= high:
        return age_rounded, "live_48h"
    return age_rounded, "live_out_of_window"


def is_learning_eligible(
    validation_mode: Optional[str],
    *,
    age_aware_enabled: bool,
) -> bool:
    """Whether this validated row may feed calibration / feedback learning."""
    if not age_aware_enabled:
        return True
    if validation_mode is None:
        # Legacy rows without a mode stay eligible.
        return True
    return validation_mode not in LEARNING_EXCLUDED_MODES


def age_aware_learning_sql(
    *,
    enabled: bool,
    alias: str = "p",
) -> tuple[str, list[str]]:
    """SQL fragment + params excluding forced_early when age-aware is ON.

    Legacy NULL modes remain eligible. Returns ("", []) when disabled.
    """
    if not enabled:
        return "", []
    clause = (
        f"AND ({alias}.validation_mode IS NULL "
        f"OR {alias}.validation_mode <> %s)"
    )
    return clause, ["forced_early"]
