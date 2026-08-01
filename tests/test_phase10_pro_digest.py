"""Tests for T10.10 Pro workflow digests (structured critic)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from phase_10.digest_critic import (
    dry_run_critic,
    parse_critic_response,
    run_critic,
)
from phase_10.digest_snapshot import (
    MAX_SNAPSHOT_CHARS,
    _errors_section,
    _search_plan_section,
    _truncate_snapshot,
    build_digest_snapshot,
)
from phase_10.digests import run_pro_digest
from phase_10.models import (
    BudgetDecision,
    BudgetSnapshot,
    DigestRecord,
    JobFlags,
    SearchPlan,
)
from phase_10.tick import HANDLERS, run_agentic_tick


def _settings(**overrides):
    from config.settings import Settings

    base = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://test",
        agentic_apify_daily_cap_usd=25.0,
        agentic_apify_monthly_cap_usd=500.0,
        agentic_gemini_daily_cap_usd=10.0,
        agentic_gemini_monthly_cap_usd=200.0,
        agentic_general_refresh_interval_hours=3.0,
        agentic_niche_scrape_interval_hours=24.0,
        agentic_pro_digest_interval_hours=24.0,
        agentic_validation_limit=50,
        agentic_feedback_limit=20,
        agentic_pro_digest_model="gemini-3.1-pro-preview",
        agentic_pro_digest_dry_run=True,
    )
    base.update(overrides)
    return Settings(**base)


def test_parse_critic_response_structured() -> None:
    raw = """
    {
      "severity": "warn",
      "summary_markdown": "Budget tight.",
      "findings": [
        {
          "title": "Gemini near cap",
          "severity": "critical",
          "category": "budget",
          "evidence": "gemini_daily_pct=95",
          "suggested_action": "Pause feedback LLM or raise cap."
        }
      ],
      "budget_warning": "95% of daily Gemini"
    }
    """
    result = parse_critic_response(raw, model="gemini-3.1-pro-preview")
    assert result.severity == "critical"  # rolled up from findings
    assert result.findings[0]["category"] == "budget"
    assert "Budget tight" in result.summary_markdown
    assert result.budget_warning is not None


def test_parse_critic_response_malformed() -> None:
    result = parse_critic_response("not-json {{{", model="gemini-3.1-pro-preview")
    assert result.severity == "warn"
    assert result.findings == []
    assert "unparseable" in result.summary_markdown.lower()
    assert "parse_error" in result.payload


def test_dry_run_critic_warns_on_errors() -> None:
    snap = {
        "errors": [{"source": "job_runs", "detail": "failed: boom"}],
        "budget": {"gemini_daily_pct": 90},
    }
    result = dry_run_critic(snap, model="gemini-3.1-pro-preview")
    assert result.severity == "warn"
    assert result.cost_usd == 0.0
    assert result.payload.get("dry_run") is True
    assert len(result.findings) >= 2


def test_search_plan_redacts_accounts() -> None:
    plan = SearchPlan(
        terms=("fintech", "saas"),
        seed_accounts=("https://linkedin.com/in/alice", "https://linkedin.com/in/bob"),
        weights_by_niche={"fintech": 1.0},
        updated_at="2026-07-25T00:00:00+00:00",
        stub=False,
    )
    section = _search_plan_section(plan)
    assert section["seed_account_count"] == 2
    assert "seed_accounts" not in section
    assert section["terms"] == ["fintech", "saas"]


def test_errors_section_from_jobs_and_proofs() -> None:
    jobs = [
        {
            "job_id": "niche_scrape",
            "result_class": "failed",
            "last_result": "failed: timeout",
        },
        {
            "job_id": "general_refresh",
            "result_class": "ok",
            "last_result": "Done: ok",
        },
    ]
    proofs = {
        "recent": [
            {"id": "1", "job_id": "general_refresh", "ok": False, "summary": "bad"},
            {"id": "2", "job_id": "niche_scrape", "ok": True, "summary": "ok"},
        ]
    }
    errors = _errors_section(jobs, proofs)
    assert len(errors) == 2
    sources = {e["source"] for e in errors}
    assert sources == {"job_runs", "scrape_proof"}


def test_truncate_snapshot_omits_bulky_runs() -> None:
    snap = {
        "apify": {"run_count": 50, "runs": [{"run_id": str(i)} for i in range(100)]},
        "scrape_proofs": {
            "recent": [{"id": str(i), "payload": {"x": "y" * 500}} for i in range(20)]
        },
        "meta": {},
    }
    # Force truncation by setting a tiny max via re-call with patched constant path.
    out = _truncate_snapshot(snap, max_chars=500)
    assert out["meta"]["truncated"] is True
    assert out["apify"].get("runs_omitted") is True
    assert len(out["scrape_proofs"]["recent"]) <= 5


@patch("phase_10.digest_snapshot._apify_section", return_value={"run_count": 0})
@patch("phase_10.digest_snapshot._feedback_section", return_value={"pending": 1})
@patch(
    "phase_10.digest_snapshot._validation_section",
    return_value={"total_validated": 10, "mae": 12.0},
)
@patch("phase_10.digest_snapshot.get_search_plan")
@patch("phase_10.digest_snapshot.scrape_proof_store.list_proofs", return_value=[])
@patch("phase_10.digest_snapshot.schedule_store.load_run_rows")
@patch("phase_10.digest_snapshot.agentic_connection")
@patch("phase_10.digest_snapshot.load_job_flags")
@patch("phase_10.digest_snapshot.get_budget_snapshot")
def test_build_digest_snapshot_mocked(
    mock_budget,
    mock_flags,
    mock_conn,
    mock_rows,
    _proofs,
    mock_plan,
    _val,
    _fb,
    _apify,
) -> None:
    mock_budget.return_value = BudgetSnapshot(
        apify_used_usd=1.0,
        apify_cap_usd=25.0,
        gemini_used_usd=2.0,
        gemini_cap_usd=10.0,
    )
    mock_flags.return_value = JobFlags(pro_digest=True)
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_rows.return_value = {
        "pro_digest": {
            "last_run_at": None,
            "next_run_at": None,
            "last_result": "skipped: disabled",
        }
    }
    mock_plan.return_value = SearchPlan(
        terms=("ai",),
        seed_accounts=("https://linkedin.com/in/x",),
        weights_by_niche={"ai_tech": 1.0},
        stub=False,
    )
    snap = build_digest_snapshot(_settings())
    assert snap["budget"]["gemini_used_usd"] == 2.0
    assert snap["search_plan"]["seed_account_count"] == 1
    assert "seed_accounts" not in snap["search_plan"]
    assert snap["validation"]["mae"] == 12.0
    assert snap["feedback_queue"]["pending"] == 1
    assert snap["meta"]["policy"] == "read_only_advisory"
    assert snap["meta"]["char_count"] <= MAX_SNAPSHOT_CHARS


@patch("phase_10.digests.record_agentic_spend")
@patch("phase_10.digests.digest_store.insert_digest")
@patch("phase_10.digests.agentic_connection")
@patch("phase_10.digests.run_critic")
@patch("phase_10.digests.build_digest_snapshot", return_value={"meta": {}})
def test_run_pro_digest_persists_and_records_spend(
    _snap,
    mock_critic,
    mock_conn,
    mock_insert,
    mock_spend,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_critic.return_value = MagicMock(
        model="gemini-3.1-pro-preview",
        summary_markdown="All quiet.",
        severity="info",
        payload={"findings": []},
        findings=[],
        cost_usd=0.05,
    )
    mock_insert.return_value = DigestRecord(
        id="abc",
        created_at="2026-07-26T00:00:00+00:00",
        summary="All quiet.",
        severity="info",
    )
    detail = run_pro_digest(_settings(agentic_pro_digest_dry_run=False))
    assert "severity=info" in detail
    assert "id=abc" in detail
    mock_spend.assert_called_once()
    assert mock_spend.call_args.kwargs["job_id"] == "pro_digest"
    assert mock_spend.call_args.kwargs["provider"] == "gemini"
    assert mock_spend.call_args.kwargs["cost_usd"] == 0.05


@patch("phase_10.digests.record_agentic_spend")
@patch("phase_10.digests.digest_store.insert_digest")
@patch("phase_10.digests.agentic_connection")
@patch("phase_10.digests.build_digest_snapshot")
def test_run_pro_digest_dry_run_zero_spend(
    mock_snap,
    mock_conn,
    mock_insert,
    mock_spend,
) -> None:
    mock_snap.return_value = {"errors": [], "budget": {}}
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_insert.return_value = DigestRecord(
        id="dry",
        created_at="2026-07-26T00:00:00+00:00",
        summary="dry",
        severity="info",
    )
    detail = run_pro_digest(_settings(agentic_pro_digest_dry_run=True))
    assert "id=dry" in detail
    mock_spend.assert_not_called()


def test_run_critic_dry_run_path() -> None:
    result = run_critic({"errors": [], "budget": {}}, _settings(agentic_pro_digest_dry_run=True))
    assert result.cost_usd == 0.0
    assert result.payload.get("dry_run") is True


@patch("phase_10.tick.allow_paid_step", return_value=BudgetDecision(allowed=True))
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows", return_value={})
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_runs_pro_digest_handler(
    mock_flags,
    mock_conn,
    _rows,
    mock_upsert,
    _gate,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=False,
        niche_scrape=False,
        pro_digest=True,
        validation_worker=False,
        feedback_worker=False,
    )

    def _digest(_settings):
        return "Done: severity=info findings=1 id=x"

    result = run_agentic_tick(
        _settings(),
        now=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        handlers={"pro_digest": _digest},
    )
    pd = next(r for r in result.results if r.job_id == "pro_digest")
    assert pd.action == "ran"
    assert "severity=info" in pd.detail
    assert "pro_digest" in HANDLERS


@patch("phase_10.tick.allow_paid_step")
@patch("phase_10.tick.schedule_store.upsert_run")
@patch("phase_10.tick.schedule_store.load_run_rows", return_value={})
@patch("phase_10.tick.agentic_connection")
@patch("phase_10.tick.load_job_flags")
def test_tick_pro_digest_budget_skip(
    mock_flags,
    mock_conn,
    _rows,
    mock_upsert,
    mock_gate,
) -> None:
    mock_conn.return_value.__enter__.return_value = MagicMock()
    mock_flags.return_value = JobFlags(
        general_refresh=False,
        niche_scrape=False,
        pro_digest=True,
        validation_worker=False,
        feedback_worker=False,
    )
    mock_gate.return_value = BudgetDecision(
        allowed=False, reason="over gemini daily cap"
    )
    result = run_agentic_tick(
        _settings(),
        now=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        handlers={"pro_digest": lambda _s: "should not run"},
    )
    pd = next(r for r in result.results if r.job_id == "pro_digest")
    assert pd.action == "skipped"
    assert "over gemini daily cap" in pd.detail


def test_pricing_includes_pro_model() -> None:
    from telemetry.pricing import cost_from_tokens, get_model_rates

    rates = get_model_rates("gemini-3.1-pro-preview")
    assert rates.input_per_1m == 2.0
    assert rates.output_per_1m == 12.0
    cost = cost_from_tokens(
        "gemini-3.1-pro-preview", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert cost == 14.0
