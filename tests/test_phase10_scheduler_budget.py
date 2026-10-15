"""Tests for T10.3 scheduler tick + T10.9 budget gate / ledger helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from phase_10.budget import allow_paid_step, get_budget_snapshot
from phase_10.cost_ledger_store import record_spend, sum_spend, sum_spend_month
from phase_10.models import BudgetDecision, JobFlags
from phase_10.tick import TickJobResult, run_agentic_tick


def _settings(**overrides):
    from config.settings import Settings

    base = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://test",
        agentic_apify_daily_cap_usd=25.0,
        agentic_apify_monthly_cap_usd=500.0,
        agentic_gemini_daily_cap_usd=10.0,
        agentic_gemini_monthly_cap_usd=200.0,
        agentic_general_refresh_interval_hours=3.0,
        agentic_niche_scrape_interval_hours=24.0,
        agentic_subscriber_evidence_interval_hours=24.0,
        agentic_pro_digest_interval_hours=24.0,
        agentic_validation_limit=50,
        agentic_feedback_limit=20,
    )
    base.update(overrides)
    return Settings(**base)


def test_sum_spend_day_and_month() -> None:
    """Pure SQL helpers via mocked cursor returning SUM values."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (12.5,)

    assert sum_spend(conn, provider="apify", day=date(2026, 7, 25)) == 12.5
    assert sum_spend_month(conn, provider="apify", day=date(2026, 7, 25)) == 12.5
    assert cur.execute.call_count == 2


def test_record_spend_skips_zero() -> None:
    conn = MagicMock()
    record_spend(conn, provider="apify", job_id="general_refresh", cost_usd=0)
    conn.cursor.assert_not_called()


def test_record_spend_upserts() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    record_spend(
        conn,
        provider="apify",
        job_id="niche_scrape",
        cost_usd=1.25,
        day=date(2026, 7, 25),
    )
    conn.commit.assert_called_once()
    sql = cur.execute.call_args[0][0]
    assert "agentic_cost_ledger" in sql
    assert cur.execute.call_args[0][1] == (
        date(2026, 7, 25),
        "apify",
        "niche_scrape",
        1.25,
    )


@patch("phase_10.budget.sum_spend_month", return_value=0.0)
@patch("phase_10.budget.sum_spend", return_value=0.0)
@patch("phase_10.budget.agentic_connection")
def test_allow_paid_step_under_cap(mock_conn, _day, _month) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    decision = allow_paid_step(
        "validation_worker", "apify", settings=_settings()
    )
    assert decision == BudgetDecision(allowed=True, reason=None)


@patch("phase_10.budget.sum_spend_month", return_value=10.0)
@patch("phase_10.budget.sum_spend", return_value=25.0)
@patch("phase_10.budget.agentic_connection")
def test_allow_paid_step_over_daily(mock_conn, _day, _month) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    decision = allow_paid_step(
        "general_refresh", "apify", settings=_settings()
    )
    assert decision.allowed is False
    assert decision.reason is not None
    assert "daily cap" in decision.reason


@patch("phase_10.budget.sum_spend_month", return_value=500.0)
@patch("phase_10.budget.sum_spend", return_value=1.0)
@patch("phase_10.budget.agentic_connection")
def test_allow_paid_step_over_monthly(mock_conn, _day, _month) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    decision = allow_paid_step(
        "niche_scrape", "apify", settings=_settings()
    )
    assert decision.allowed is False
    assert "monthly cap" in (decision.reason or "")


@patch("phase_10.budget.sum_spend_month", side_effect=[5.0, 2.0])
@patch("phase_10.budget.sum_spend", side_effect=[1.5, 0.5])
@patch("phase_10.budget.agentic_connection")
def test_get_budget_snapshot_live(mock_conn, _day, _month) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    snap = get_budget_snapshot(_settings())
    assert snap.stub_caps is False
    assert snap.apify_used_usd == 1.5
    assert snap.gemini_used_usd == 0.5
    assert snap.apify_cap_usd == 25.0


@patch("phase_10.tick.is_tick_paused", return_value=False)
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows", return_value={})
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_disabled_and_stubs(
    mock_flags,
    mock_conn,
    _rows,
    mock_upsert,
    _paused,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=False,
        niche_scrape=True,
        pro_digest=True,
        validation_worker=False,
        feedback_worker=False,
        subscriber_evidence=False,
    )
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    result = run_agentic_tick(
        _settings(),
        now=now,
        handlers={},  # force stubs / no workers
    )
    by_id = {r.job_id: r for r in result.results}
    assert by_id["general_refresh"].detail == "skipped: disabled"
    assert by_id["validation_worker"].detail == "skipped: disabled"
    assert "no handler" in by_id["niche_scrape"].detail
    assert "no handler" in by_id["pro_digest"].detail


@patch("phase_10.tick.is_tick_paused", return_value=False)
@patch("phase_10.tick.allow_paid_step")
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows")
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_not_due_and_budget_skip(
    mock_flags,
    mock_conn,
    mock_rows,
    mock_upsert,
    mock_gate,
    _paused,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=True,
        niche_scrape=True,
        pro_digest=False,
        validation_worker=True,
        feedback_worker=False,
        subscriber_evidence=False,
    )
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    mock_rows.return_value = {
        "general_refresh": {
            "last_run_at": now - timedelta(hours=1),
            "next_run_at": now + timedelta(hours=2),
            "last_result": "ok",
        },
        "niche_scrape": {
            "last_run_at": None,
            "next_run_at": None,
            "last_result": None,
        },
        "validation_worker": {
            "last_run_at": None,
            "next_run_at": None,
            "last_result": None,
        },
    }
    mock_gate.side_effect = [
        BudgetDecision(allowed=True),  # validation
        BudgetDecision(allowed=False, reason="over apify daily cap"),  # niche
    ]

    def _val(_settings):
        return "Done: processed=1 validated=1 failed=0"

    def _niche(_settings):
        return "should not run"

    result = run_agentic_tick(
        _settings(),
        now=now,
        handlers={"validation_worker": _val, "niche_scrape": _niche},
    )
    by_id = {r.job_id: r for r in result.results}
    assert by_id["general_refresh"].detail == "skipped: not due"
    assert by_id["validation_worker"].action == "ran"
    assert "processed=1" in by_id["validation_worker"].detail
    assert "over apify daily cap" in by_id["niche_scrape"].detail


@patch("phase_10.tick.is_tick_paused", return_value=False)
@patch("phase_10.tick.allow_paid_step", return_value=BudgetDecision(allowed=True))
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows", return_value={})
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_runs_feedback_handler(
    mock_flags,
    mock_conn,
    _rows,
    mock_upsert,
    _gate,
    _paused,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=False,
        niche_scrape=False,
        pro_digest=False,
        validation_worker=False,
        feedback_worker=True,
        subscriber_evidence=False,
    )

    def _fb(_settings):
        return "Done: claimed=2 succeeded=2 failed=0 dead_lettered=0"

    result = run_agentic_tick(
        _settings(),
        now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        handlers={"feedback_worker": _fb},
    )
    fb = next(r for r in result.results if r.job_id == "feedback_worker")
    assert fb == TickJobResult(
        "feedback_worker",
        "ran",
        "Done: claimed=2 succeeded=2 failed=0 dead_lettered=0",
    )
    mock_upsert.assert_called()


@patch("phase_10.tick.is_tick_paused", return_value=False)
@patch("phase_10.tick.allow_paid_step", return_value=BudgetDecision(allowed=True))
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows", return_value={})
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_runs_subscriber_evidence_handler(
    mock_flags,
    mock_conn,
    _rows,
    mock_upsert,
    _gate,
    _paused,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=False,
        niche_scrape=False,
        pro_digest=False,
        validation_worker=False,
        feedback_worker=False,
        subscriber_evidence=True,
    )

    def _sub(_settings):
        return "ran=1 skipped=0 failed=0 (sports-user-1:ran)"

    result = run_agentic_tick(
        _settings(),
        now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        handlers={"subscriber_evidence": _sub},
    )
    job = next(r for r in result.results if r.job_id == "subscriber_evidence")
    assert job.action == "ran"
    assert "sports-user-1:ran" in job.detail


@patch("phase_10.tick.is_tick_paused", return_value=True)
@patch("phase_10.tick.record_tick_heartbeat")
def test_tick_respects_global_pause(mock_heartbeat, _paused) -> None:
    result = run_agentic_tick(_settings())
    assert len(result.results) == 1
    assert result.results[0].job_id == "_tick"
    assert result.results[0].detail == "skipped: paused"
    mock_heartbeat.assert_called_once_with("paused — no jobs executed")


@patch("phase_10.tick.is_tick_paused", return_value=True)
@patch("phase_10.tick.agentic_connection")
def test_tick_force_runs_when_paused(mock_conn, _paused) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    with patch("phase_10.tick.schedule_store.load_run_rows", return_value={}), patch(
        "phase_10.tick.load_job_flags"
    ) as mock_flags, patch("phase_10.tick.schedule_store.upsert_run"), patch(
        "phase_10.tick.record_tick_heartbeat"
    ):
        mock_flags.return_value = JobFlags(
            general_refresh=False,
            niche_scrape=False,
            pro_digest=False,
            validation_worker=False,
            feedback_worker=False,
            subscriber_evidence=False,
        )
        result = run_agentic_tick(
            _settings(),
            now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
            handlers={},
            force=True,
        )
    assert any(r.job_id != "_tick" for r in result.results)
