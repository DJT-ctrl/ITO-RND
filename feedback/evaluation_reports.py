"""Load and discover persisted Phase E offline evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.paths import resolve_data_path
from config.settings import Settings
from feedback.evaluation import FeedbackEvaluationReport

EVAL_FEEDBACK_GLOB = "eval_feedback_*.json"


def telemetry_eval_dir(settings: Settings) -> Path:
    return resolve_data_path(settings.telemetry_data_dir)


def list_eval_feedback_paths(settings: Settings) -> list[Path]:
    """Return eval_feedback_*.json paths newest-first by filename stamp."""
    directory = telemetry_eval_dir(settings)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(EVAL_FEEDBACK_GLOB), reverse=True)


def latest_eval_feedback_path(settings: Settings) -> Optional[Path]:
    paths = list_eval_feedback_paths(settings)
    return paths[0] if paths else None


def load_eval_feedback_report(path: Path) -> FeedbackEvaluationReport:
    """Parse one saved report; raises ValueError on invalid JSON/schema."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid eval feedback JSON at {path}: {exc}") from exc
    return FeedbackEvaluationReport.model_validate(payload)


def load_latest_eval_feedback_report(
    settings: Settings,
) -> tuple[Optional[FeedbackEvaluationReport], Optional[Path]]:
    path = latest_eval_feedback_path(settings)
    if path is None:
        return None, None
    return load_eval_feedback_report(path), path
