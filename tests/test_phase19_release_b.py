"""Unit tests for Phase 19 Release B collection guards, curator, and gaps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from phase_19.budget_guard import evaluate_collection_gate
from phase_19.collector import process_subscriber, run_subscriber_collection
from phase_19.curator import curate_candidates
from phase_19.gaps import assess_gaps
from phase_19.models import SubscriberEvidenceBrief
from phase_19.planner import build_baseline_plan


def _brief_dict(**overrides) -> dict:
    values = {
        "id": "brief-1",
        "subscriber_id": "sports-user-1",
        "public_profile_url": "https://www.linkedin.com/in/sports-user-1/",
        "profile_authorized": True,
        "role_description": "Football academy founder",
        "primary_niche": "sports",
        "sub_niche": "football coaching",
        "target_audience": "academy owners",
        "objectives": ["authority"],
        "locale": "United Kingdom",
        "seed_accounts": ["https://www.linkedin.com/in/peer-coach/"],
        "status": "approved",
    }
    values.update(overrides)
    return values


def _plan_dict(**overrides) -> dict:
    values = {
        "id": "plan-1",
        "brief_id": "brief-1",
        "provider": "apify",
        "baseline_budget_usd": 10.0,
        "daily_candidate_limit": 100,
        "source_priorities": [
            "subscriber_public_profile",
            "approved_seed_accounts",
            "niche_keyword_queries",
        ],
        "proposed_queries": ["sports football coaching"],
        "rationale": "capped",
        "status": "approved",
    }
    values.update(overrides)
    return values


def test_curate_rejects_duplicates_and_low_content() -> None:
    posts = [
        {"id": "p1", "content": "x" * 50, "author": {"publicIdentifier": "a"}},
        {"id": "p1", "content": "y" * 50, "author": {"publicIdentifier": "a"}},
        {"id": "p2", "content": "short", "author": {"publicIdentifier": "b"}},
        {"id": "p3", "content": "z" * 60, "author": {"publicIdentifier": "c"}},
    ]
    curated = curate_candidates(
        posts,
        source_type="niche_keyword_queries",
        known_post_ids=set(),
        max_accept=10,
    )
    by_id = {}
    for item in curated:
        by_id.setdefault(item.post_id, []).append((item.decision, item.rejection_reason))
    assert by_id["p1"][0] == ("accepted", None)
    assert by_id["p1"][1] == ("rejected", "duplicate")
    assert by_id["p2"] == [("rejected", "low_content")]
    assert by_id["p3"] == [("accepted", None)]


def test_assess_gaps_noops_when_fresh_and_diverse() -> None:
    stats = {
        "accepted_count": 20,
        "newest_at": datetime.now(timezone.utc),
        "dominant_author_share": 0.3,
    }
    result = assess_gaps(stats, brief=_brief_dict())
    assert result.needs_collection is False


def test_assess_gaps_detects_coverage_and_freshness() -> None:
    stats = {
        "accepted_count": 2,
        "newest_at": datetime.now(timezone.utc) - timedelta(hours=72),
        "dominant_author_share": 0.9,
    }
    result = assess_gaps(stats, brief=_brief_dict(seed_accounts=[]))
    assert result.needs_collection is True
    assert any("coverage_gap" in r for r in result.reasons)
    assert any("freshness_gap" in r for r in result.reasons)
    assert result.recommended_seeds  # recorded only, not auto-collected


@patch("phase_19.budget_guard.allow_paid_step")
@patch("phase_19.budget_guard.evidence_store.budget_snapshot")
def test_budget_gate_blocks_paused_and_exhausted(mock_snap, mock_allow) -> None:
    mock_allow.return_value = MagicMock(allowed=True, reason=None)
    mock_snap.return_value = {
        "lifetime_baseline_spent_usd": 0.0,
        "day_candidates": 0,
        "day_spent_usd": 0.0,
    }
    paused = evaluate_collection_gate(
        MagicMock(), brief=_brief_dict(status="paused"), plan=_plan_dict()
    )
    assert paused.allowed is False
    assert "paused" in paused.reason

    mock_snap.return_value = {
        "lifetime_baseline_spent_usd": 10.0,
        "day_candidates": 0,
        "day_spent_usd": 0.0,
    }
    exhausted = evaluate_collection_gate(
        MagicMock(), brief=_brief_dict(), plan=_plan_dict()
    )
    assert exhausted.allowed is False
    assert "budget exhausted" in exhausted.reason


@patch("phase_19.collector.evaluate_collection_gate")
def test_collection_skips_without_approval_gate(mock_gate) -> None:
    mock_gate.return_value = MagicMock(
        allowed=False,
        reason="plan not approved",
        remaining_budget_usd=0,
        remaining_candidates=0,
    )
    result = run_subscriber_collection(
        MagicMock(),
        _brief_dict(status="draft"),
        _plan_dict(status="proposed"),
        job_kind="baseline",
    )
    assert result.action == "skipped"
    assert "plan not approved" in result.detail


@patch("phase_19.collector.record_agentic_spend")
@patch("phase_19.collector.evidence_store")
@patch("phase_19.collector.evaluate_collection_gate")
def test_baseline_collection_persists_receipt(mock_gate, mock_store, _spend) -> None:
    mock_gate.return_value = MagicMock(
        allowed=True,
        remaining_budget_usd=10.0,
        remaining_candidates=100,
    )
    mock_store.create_collection_job.return_value = {"id": "job-1"}
    mock_store.known_post_ids_for_subscriber.return_value = set()
    mock_store.save_receipt.return_value = {
        "id": "receipt-1",
        "summary": "baseline: accepted=1 rejected=0 usd=0.1000",
    }

    def _profile(urls, *, max_posts, settings):
        return (
            [
                {
                    "id": "post-1",
                    "content": "A useful sports coaching insight about academy growth.",
                    "author": {"publicIdentifier": "sports-user-1"},
                }
            ],
            0.1,
            "run-1",
        )

    def _query(queries, *, max_posts, settings):
        return [], 0.0, None

    def _ingest(posts, **kwargs):
        return len(posts)

    result = run_subscriber_collection(
        MagicMock(),
        _brief_dict(seed_accounts=[]),
        _plan_dict(proposed_queries=[]),
        job_kind="baseline",
        profile_collector=_profile,
        query_collector=_query,
        ingest_fn=_ingest,
    )
    assert result.action == "ran"
    assert result.receipt_id == "receipt-1"
    mock_store.save_evidence_item.assert_called()
    mock_store.finish_collection_job.assert_called()
    assert mock_store.finish_collection_job.call_args.kwargs["status"] == "completed"


@patch("phase_19.collector.run_subscriber_collection")
@patch("phase_19.collector.evidence_store")
def test_process_subscriber_skips_daily_when_no_gap(mock_store, mock_run) -> None:
    mock_store.baseline_completed.return_value = True
    mock_store.coverage_stats.return_value = {
        "accepted_count": 30,
        "newest_at": datetime.now(timezone.utc),
        "dominant_author_share": 0.2,
    }
    mock_store.create_collection_job.return_value = {"id": "job-skip"}
    result = process_subscriber(MagicMock(), _brief_dict(), _plan_dict())
    assert result.action == "skipped"
    assert "no coverage gap" in result.detail
    mock_run.assert_not_called()


def test_revise_plan_sql_allows_multiple_plans_per_brief() -> None:
    """save_brief_and_plan must INSERT a new plan after superseding old ones."""
    from phase_19 import evidence_store
    from phase_19.models import BaselinePlanProposal

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    brief_row = (
        "brief-1",
        "sports-user-1",
        "https://www.linkedin.com/in/sports-user-1/",
        True,
        "role",
        "sports",
        "football",
        "owners",
        ["authority"],
        "UK",
        [],
        "draft",
        datetime.now(timezone.utc),
        datetime.now(timezone.utc),
    )
    plan_row = (
        "plan-2",
        "brief-1",
        "apify",
        10.0,
        100,
        ["subscriber_public_profile"],
        ["sports"],
        "rationale",
        "proposed",
        datetime.now(timezone.utc),
        None,
    )
    cur.fetchone.side_effect = [brief_row, plan_row]

    brief = SubscriberEvidenceBrief(
        subscriber_id="sports-user-1",
        public_profile_url="https://www.linkedin.com/in/sports-user-1/",
        profile_authorized=True,
        role_description="role",
        primary_niche="sports",
        sub_niche="football",
        target_audience="owners",
    )
    plan = build_baseline_plan(brief)
    saved_brief, saved_plan = evidence_store.save_brief_and_plan(conn, brief, plan)

    assert saved_brief["id"] == "brief-1"
    assert saved_plan["id"] == "plan-2"
    sqls = [call.args[0] for call in cur.execute.call_args_list]
    assert any("status = 'superseded'" in sql for sql in sqls)
    assert sum("INSERT INTO subscriber_baseline_plans" in sql for sql in sqls) == 1
    # Schema no longer UNIQUE on brief_id; revise path inserts rather than upserts.
    assert not any("ON CONFLICT (brief_id)" in sql for sql in sqls)


def test_membership_isolation_query_scopes_by_subscriber() -> None:
    from phase_19 import evidence_store

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [("post-a",)]

    ids = evidence_store.known_post_ids_for_subscriber(conn, "user-a")
    assert ids == {"post-a"}
    sql, params = cur.execute.call_args[0]
    assert "subscriber_evidence_membership" in sql
    assert params == ("user-a",)


def test_merge_unique_prefers_private_before_global() -> None:
    from storage.similarity import _merge_unique_rows

    private = [{"post_id": "p1", "content": "private"}]
    shared = [{"post_id": "p2", "content": "shared"}]
    global_rows = [{"post_id": "p1", "content": "dup"}, {"post_id": "p3", "content": "g"}]
    merged = _merge_unique_rows(private, shared, global_rows, limit=10)
    assert [r["post_id"] for r in merged] == ["p1", "p2", "p3"]
