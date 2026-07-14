"""Tests for persisted offline evaluation report discovery/loading."""

import json
from datetime import datetime, timezone
from pathlib import Path

from feedback.evaluation import FeedbackEvaluationReport
from feedback.evaluation_reports import (
    latest_eval_feedback_path,
    load_eval_feedback_report,
    load_latest_eval_feedback_report,
)


class _Settings:
    telemetry_data_dir: str

    def __init__(self, telemetry_data_dir: str) -> None:
        self.telemetry_data_dir = telemetry_data_dir


def _sample_report(**overrides) -> FeedbackEvaluationReport:
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc),
        "total_rows": 40,
        "training_rows": 10,
        "holdout_rows": 30,
        "global_mean_delta": 1.5,
        "global_calibration_ready": False,
        "arms": [
            {
                "arm": "raw_no_feedback",
                "calibration_enabled": False,
                "feedback_injection_enabled": False,
                "sample_count": 30,
                "mae": 8.0,
                "pct_within_10": 70.0,
                "per_cluster_mae": {"short_prose_micro": 8.0},
            }
        ],
        "notes": ["Holdout rows are excluded from all calibration statistics."],
    }
    payload.update(overrides)
    return FeedbackEvaluationReport.model_validate(payload)


def test_latest_eval_feedback_path_picks_newest_filename(tmp_path: Path):
    telemetry = tmp_path / "telemetry"
    telemetry.mkdir(parents=True)
    older = telemetry / "eval_feedback_2026-07-12_100000Z.json"
    newer = telemetry / "eval_feedback_2026-07-13_120000Z.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")

    settings = _Settings(str(telemetry))
    assert latest_eval_feedback_path(settings) == newer


def test_load_eval_feedback_report_round_trip(tmp_path: Path):
    path = tmp_path / "eval_feedback_2026-07-13_101130Z.json"
    report = _sample_report()
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    loaded = load_eval_feedback_report(path)
    assert loaded.holdout_rows == 30
    assert loaded.arms[0].mae == 8.0
    assert loaded.global_calibration_ready is False


def test_load_latest_eval_feedback_report_empty(tmp_path: Path):
    telemetry = tmp_path / "telemetry"
    telemetry.mkdir(parents=True)
    report, path = load_latest_eval_feedback_report(_Settings(str(telemetry)))
    assert report is None
    assert path is None
