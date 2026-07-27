"""Tests for scheduled backup / DR helpers (issue #15)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from storage.dr_backup import (
    BackupRunResult,
    prune_local_dumps,
    run_scheduled_backup,
    simulate_restore_drill_timings,
    upload_dump_to_s3,
    write_backup_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_DOC = REPO_ROOT / "docs" / "ops" / "BACKUP_DR.md"
DRILL_REPORT = REPO_ROOT / "docs" / "ops" / "RESTORE_DRILL_LATEST.json"
ALERTS = REPO_ROOT / "deploy" / "telemetry" / "alerts" / "backup.yml"
TIMER = REPO_ROOT / "deploy" / "ito-db-backup.timer"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"


def fake_settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="fake",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://ito:secret@localhost:5432/ito_posts",
    )


def test_backup_dr_docs_and_schedule_exist():
    assert BACKUP_DOC.is_file()
    text = BACKUP_DOC.read_text(encoding="utf-8")
    assert "RPO" in text and "RTO" in text
    assert "≤ 24 hours" in text or "24 hours" in text
    assert "≤ 4 hours" in text or "4 hours" in text
    assert TIMER.is_file()
    assert "OnCalendar=" in TIMER.read_text(encoding="utf-8")
    assert ALERTS.is_file()
    assert BACKLOG.is_file()
    assert "Issue #15 — requirements" in BACKLOG.read_text(encoding="utf-8")


def test_backup_alert_rules_parse():
    text = ALERTS.read_text(encoding="utf-8")
    assert "BackupJobFailed" in text
    assert "BackupJobStale" in text
    assert "ito_backup_last_ok" in text
    assert "ito_backup_last_success_timestamp" in text


def test_prune_local_dumps_keeps_newest(tmp_path):
    for name in [
        "posts_daily_20260101T000000Z.dump",
        "posts_daily_20260102T000000Z.dump",
        "posts_daily_20260103T000000Z.dump",
    ]:
        (tmp_path / name).write_bytes(b"x")
    removed = prune_local_dumps(tmp_path, keep=2)
    assert len(removed) == 1
    assert "20260101" in removed[0]
    remaining = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert remaining == [
        "posts_daily_20260102T000000Z.dump",
        "posts_daily_20260103T000000Z.dump",
    ]


def test_upload_dump_to_s3_invokes_aws_cli(tmp_path):
    dump = tmp_path / "posts_daily_test.dump"
    dump.write_bytes(b"abc")
    fake = MagicMock(returncode=0, stderr="")
    with patch("storage.dr_backup.subprocess.run", return_value=fake) as mock_run:
        uri = upload_dump_to_s3(dump, bucket="ito-backups", prefix="ito/postgres")
    assert uri == "s3://ito-backups/ito/postgres/posts_daily_test.dump"
    assert mock_run.call_args.args[0][:3] == ["aws", "s3", "cp"]


def test_write_backup_status_emits_prometheus_textfile(tmp_path):
    status = tmp_path / "status.json"
    textfile = tmp_path / "ito_backup.prom"
    result = BackupRunResult(
        ok=True,
        dump_path="x.dump",
        s3_uri="s3://b/k",
        bytes=10,
        duration_seconds=1.5,
        error=None,
        finished_at="2026-07-17T12:00:00+00:00",
        pruned_local=[],
    )
    write_backup_status(result, status_json=status, textfile=textfile)
    body = textfile.read_text(encoding="utf-8")
    assert "ito_backup_last_ok 1" in body
    assert "ito_backup_last_success_timestamp" in body
    assert json.loads(status.read_text(encoding="utf-8"))["ok"] is True


def test_run_scheduled_backup_success_path(tmp_path):
    dump = tmp_path / "posts_daily_20260717T000000Z.dump"
    settings = fake_settings()
    with patch("storage.dr_backup.create_backup", return_value=dump) as mock_create:
        dump.write_bytes(b"dump-bytes")
        with patch("storage.dr_backup.upload_dump_to_s3", return_value="s3://b/k") as mock_up:
            result = run_scheduled_backup(
                settings,
                backup_dir=str(tmp_path),
                s3_bucket="b",
                keep_local=5,
                status_json=tmp_path / "status.json",
                textfile=tmp_path / "t.prom",
            )
    mock_create.assert_called_once()
    mock_up.assert_called_once()
    assert result.ok is True
    assert result.s3_uri == "s3://b/k"
    assert (tmp_path / "t.prom").is_file()


def test_run_scheduled_backup_records_failure(tmp_path):
    settings = fake_settings()
    with patch("storage.dr_backup.create_backup", side_effect=RuntimeError("pg_dump failed")):
        with pytest.raises(RuntimeError, match="pg_dump failed"):
            run_scheduled_backup(
                settings,
                backup_dir=str(tmp_path),
                s3_bucket=None,
                status_json=tmp_path / "status.json",
                textfile=tmp_path / "t.prom",
            )
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is False
    assert "ito_backup_last_ok 0" in (tmp_path / "t.prom").read_text(encoding="utf-8")


def test_simulate_restore_drill_meets_rpo_rto_and_writes_report(tmp_path):
    payload = simulate_restore_drill_timings(
        dump_age_seconds=1800,
        restore_duration_seconds=90,
    )
    assert payload["ok"] is True
    assert payload["rpo_met"] is True
    assert payload["rto_met"] is True
    report = tmp_path / "RESTORE_DRILL_LATEST.json"
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert report.is_file()


def test_committed_restore_drill_report_exists():
    assert DRILL_REPORT.is_file()
    payload = json.loads(DRILL_REPORT.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["rpo_met"] is True
    assert payload["rto_met"] is True


def test_compose_mounts_backup_textfile_and_alerts():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "node-exporter-textfile" in compose
    assert "collector.textfile.directory" in compose
    assert "./deploy/telemetry/alerts:/etc/prometheus/alerts:ro" in compose
    prom = (REPO_ROOT / "deploy" / "telemetry" / "prometheus.yml").read_text(encoding="utf-8")
    assert "rule_files:" in prom
