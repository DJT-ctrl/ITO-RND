"""Persistent dashboard overrides for feedback-loop feature flags.

Env vars remain the base; this JSON file (written from the Feedback Loop tab)
overrides them so toggles affect Streamlit, the worker, and predict without
editing ``.env``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from feedback.audit import append_override_audit

logger = logging.getLogger(__name__)

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


def save_overrides(
    updates: dict[str, Any],
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Merge ``updates`` into the override file and return the full set."""
    previous = load_overrides()
    current = dict(previous)
    for key, value in updates.items():
        if key not in ALLOWED_KEYS:
            continue
        current[key] = value
    OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OVERRIDE_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(OVERRIDE_PATH)
    try:
        append_override_audit(
            action="save",
            previous=previous,
            current=current,
            actor=actor,
            path=OVERRIDE_PATH.parent
            / "telemetry"
            / "feedback_loop_overrides.jsonl",
        )
    except OSError:
        logger.exception("Could not append feedback-loop override audit event")
    return current


def clear_overrides(*, actor: str | None = None) -> None:
    previous = load_overrides()
    if OVERRIDE_PATH.exists():
        OVERRIDE_PATH.unlink()
    try:
        append_override_audit(
            action="clear",
            previous=previous,
            current={},
            actor=actor,
            path=OVERRIDE_PATH.parent
            / "telemetry"
            / "feedback_loop_overrides.jsonl",
        )
    except OSError:
        logger.exception("Could not append feedback-loop override audit event")


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
