"""Persistent dashboard overrides for feedback-loop feature flags.

Env vars remain the base; this JSON file (written from the Feedback Loop tab)
overrides them so toggles affect Streamlit, the worker, and predict without
editing ``.env``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERRIDE_PATH = _PROJECT_ROOT / "data" / "feedback_loop_overrides.json"

# Keys that the Feedback Loop settings panel may write.
ALLOWED_KEYS = frozenset(
    {
        "validation_calibration_enabled",
        "validation_feedback_enabled",
        "validation_feedback_injection_enabled",
        "validation_feedback_injection_limit",
        "validation_calibration_n_min",
        "validation_cluster_n_min",
    }
)


def load_overrides() -> dict[str, Any]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        raw = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in ALLOWED_KEYS}


def save_overrides(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the override file and return the full set."""
    current = load_overrides()
    for key, value in updates.items():
        if key not in ALLOWED_KEYS:
            continue
        current[key] = value
    OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE_PATH.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return current


def clear_overrides() -> None:
    if OVERRIDE_PATH.exists():
        OVERRIDE_PATH.unlink()


def apply_overrides_to_settings(settings: Any) -> Any:
    """Return a new Settings with any persisted dashboard overrides applied."""
    from dataclasses import replace

    overrides = load_overrides()
    if not overrides:
        return settings
    allowed = {k: v for k, v in overrides.items() if hasattr(settings, k)}
    if not allowed:
        return settings
    return replace(settings, **allowed)
