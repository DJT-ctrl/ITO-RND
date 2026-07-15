"""Tests for Phase I feedback job queue and G+ auto-approve gating."""

from unittest.mock import MagicMock
from uuid import uuid4

from feedback.batch import resolve_hybrid_review_status
from feedback.queue import (
    FeedbackQueueBacklog,
    claim_feedback_jobs,
    count_feedback_queue_backlog,
    enqueue_feedback_job,
    mark_feedback_job_done,
    mark_feedback_job_failed,
)
from feedback.summarize import build_rollup_summary_text, structured_bias_line


def test_build_rollup_summary_text_overestimate():
    text = build_rollup_summary_text(
        "short_prose_micro",
        sample_count=12,
        mean_delta=-5.5,
        std_delta=3.0,
    )
    assert "mean_delta=-5.5" in text
    assert "overestimates" in text
    assert "N=12" in text


def test_structured_bias_line_jsonish():
    line = structured_bias_line(mean_delta=4.25, sample_count=9)
    assert '"cluster_mean_delta": 4.25' in line
    assert '"direction": "underestimated"' in line
    assert '"N": 9' in line


def test_resolve_hybrid_review_status_defaults_pending():
    settings = MagicMock()
    settings.validation_feedback_auto_approve_enabled = False
    settings.validation_feedback_auto_approve_delta_max = 40.0
    settings.validation_feedback_auto_approve_max_per_day = 20
    status, by = resolve_hybrid_review_status(
        settings, prediction_delta=12.0, auto_approved_today=0
    )
    assert status == "pending"
    assert by is None


def test_resolve_hybrid_review_status_auto_approves_when_gated():
    settings = MagicMock()
    settings.validation_feedback_auto_approve_enabled = True
    settings.validation_feedback_auto_approve_delta_max = 40.0
    settings.validation_feedback_auto_approve_max_per_day = 20
    status, by = resolve_hybrid_review_status(
        settings, prediction_delta=12.0, auto_approved_today=0
    )
    assert status == "approved"
    assert by == "auto_approve"


def test_resolve_hybrid_review_status_respects_delta_and_daily_cap():
    settings = MagicMock()
    settings.validation_feedback_auto_approve_enabled = True
    settings.validation_feedback_auto_approve_delta_max = 40.0
    settings.validation_feedback_auto_approve_max_per_day = 2
    status, _ = resolve_hybrid_review_status(
        settings, prediction_delta=50.0, auto_approved_today=0
    )
    assert status == "pending"
    status, _ = resolve_hybrid_review_status(
        settings, prediction_delta=10.0, auto_approved_today=2
    )
    assert status == "pending"


def test_enqueue_feedback_job_sql():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    pid = uuid4()
    enqueue_feedback_job(conn, pid, max_attempts=3)
    assert cursor.execute.called
    sql = cursor.execute.call_args[0][0]
    assert "INSERT INTO feedback_jobs" in sql
    assert pid in cursor.execute.call_args[0][1]
    conn.commit.assert_called_once()


def test_claim_feedback_jobs_returns_ids():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    pid = uuid4()
    cursor.fetchall.return_value = [(pid,)]
    claimed = claim_feedback_jobs(conn, limit=5)
    assert claimed == [pid]
    assert "FOR UPDATE SKIP LOCKED" in cursor.execute.call_args[0][0]


def test_mark_feedback_job_failed_dead_letters():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = ("dead",)
    status = mark_feedback_job_failed(conn, uuid4(), "boom")
    assert status == "dead"


def test_mark_feedback_job_done():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    mark_feedback_job_done(conn, uuid4())
    assert "status = 'done'" in cursor.execute.call_args[0][0]


def test_count_feedback_queue_backlog():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [
        ("pending", 3),
        ("done", 10),
        ("dead", 1),
    ]
    backlog = count_feedback_queue_backlog(conn)
    assert isinstance(backlog, FeedbackQueueBacklog)
    assert backlog.pending == 3
    assert backlog.done == 10
    assert backlog.dead == 1
    assert backlog.open_count == 3
