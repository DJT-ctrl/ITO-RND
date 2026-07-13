"""Orchestrate and persist the Phase E offline feedback evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import Settings
from feedback.evaluation import FeedbackEvaluationReport, run_offline_replay
from feedback.evaluation_store import fetch_replay_rows
from storage.vector_store import create_schema, get_connection


def run_and_save_offline_evaluation(
    settings: Settings,
    *,
    holdout_size: int = 30,
) -> tuple[FeedbackEvaluationReport, Path]:
    """Load validated history, run replay, and save a versioned JSON report."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = fetch_replay_rows(conn)
    finally:
        conn.close()

    report = run_offline_replay(
        rows,
        holdout_size=holdout_size,
        global_n_min=settings.validation_calibration_n_min,
        cluster_n_min=settings.validation_cluster_n_min,
    )
    output_dir = resolve_data_path(settings.telemetry_data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"eval_feedback_{utc_artifact_stamp()}.json"
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return report, path
