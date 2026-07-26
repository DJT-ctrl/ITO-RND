"""Tests for T10.4/T10.5 corpus refresh + T10.5.5 proof helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import Settings
from phase_10.corpus_refresh import allocate_niche_budgets, run_corpus_refresh
from phase_10.models import BudgetDecision, JobFlags, ScrapeProof
from phase_10.tick import HANDLERS, STUB_REASONS
from phase_10.topics import queries_for_niche
from processors.run_pipeline import run_pipeline


def _settings(**overrides) -> Settings:
    base = dict(
        apify_api_token="t",
        apify_actor_id="a",
        apify_profile_actor_id="p",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://test",
        agentic_general_max_posts=20,
        agentic_niche_max_posts_total=40,
        agentic_niche_stale_hours=20.0,
        agentic_scrape_with_gemini=False,
        agentic_apify_daily_cap_usd=25.0,
        agentic_apify_monthly_cap_usd=500.0,
        agentic_gemini_daily_cap_usd=10.0,
        agentic_gemini_monthly_cap_usd=200.0,
    )
    base.update(overrides)
    return Settings(**base)


def test_queries_for_niche_fintech_nonempty() -> None:
    qs = queries_for_niche("fintech")
    assert qs
    assert "fintech" in qs[0] or any("fintech" in q for q in qs)
    assert len(qs) <= 5


def test_queries_for_niche_other_empty() -> None:
    assert queries_for_niche("other") == []
    assert queries_for_niche("not_a_niche") == []


def test_allocate_niche_budgets_by_weight() -> None:
    budgets = allocate_niche_budgets({"fintech": 0.75, "sports": 0.25}, 20)
    assert budgets["fintech"] >= budgets["sports"]
    assert sum(budgets.values()) <= 20
    assert all(v >= 1 for v in budgets.values())


def test_allocate_empty() -> None:
    assert allocate_niche_budgets({}, 20) == {}
    assert allocate_niche_budgets({"fintech": 1.0}, 0) == {}


@patch("processors.run_pipeline.load_raw_posts")
def test_run_pipeline_raw_posts_skips_directory_load(mock_load) -> None:
    settings = _settings(database_url="")
    store = MagicMock()
    store.save.return_value = Path("/tmp/out.csv")
    store.save_jsonl.return_value = Path("/tmp/out.jsonl")

    with patch("processors.run_pipeline.PostAnalyser") as mock_analyser_cls:
        analyser = MagicMock()
        analyser.compute_python_features.side_effect = lambda post: {
            "post_id": post.get("id"),
            "content": "hello world " * 5,
            "word_count": 10,
            "likes": 1,
            "comments": 0,
            "shares": 0,
            "total_engagement": 1,
        }
        mock_analyser_cls.return_value = analyser
        with patch(
            "processors.run_pipeline.finalize_analysed_records",
            return_value=([{"post_id": "1"}], []),
        ):
            with patch("processors.run_pipeline.register_analysed_bundle"):
                with patch("processors.run_pipeline.build_snapshot", side_effect=ValueError):
                    run_pipeline(
                        settings=settings,
                        store=store,
                        raw_posts=[{"id": "1", "content": "x" * 50}],
                        source_scans=["linkedin_test.json"],
                    )
    mock_load.assert_not_called()


@patch("phase_10.corpus_refresh._persist_proof")
@patch("phase_10.corpus_refresh.allow_paid_step")
def test_corpus_refresh_budget_skip(mock_gate, mock_persist) -> None:
    mock_gate.return_value = BudgetDecision(allowed=False, reason="over apify daily cap")
    mock_persist.side_effect = lambda settings, **kw: ScrapeProof(
        job_id=kw["job_id"],
        niche=kw.get("niche"),
        summary=kw["payload"]["summary"],
        payload=kw["payload"],
        ok=False,
    )
    proof = run_corpus_refresh(
        "general_refresh",
        ["ai"],
        max_posts=5,
        settings=_settings(),
    )
    assert proof.ok is False
    assert "over apify" in proof.summary


@patch("phase_10.corpus_refresh._persist_proof")
@patch("phase_10.corpus_refresh.allow_paid_step", return_value=BudgetDecision(allowed=True))
def test_corpus_refresh_no_queries(mock_gate, mock_persist) -> None:
    mock_persist.side_effect = lambda settings, **kw: ScrapeProof(
        job_id=kw["job_id"],
        summary=kw["payload"]["summary"],
        payload=kw["payload"],
        ok=True,
    )
    proof = run_corpus_refresh(
        "general_refresh",
        [],
        max_posts=5,
        settings=_settings(),
    )
    assert "no queries" in proof.summary


@patch("phase_10.corpus_refresh.run_db_ingest", return_value=2)
@patch("phase_10.corpus_refresh.run_embeddings", return_value=Path("/tmp/x.npy"))
@patch("phase_10.corpus_refresh.load_analysed_jsonl")
@patch("phase_10.corpus_refresh.run_pipeline")
@patch("phase_10.corpus_refresh.run_sample_collection")
@patch("phase_10.corpus_refresh.record_agentic_spend")
@patch("phase_10.corpus_refresh._existing_post_ids", return_value={"old"})
@patch("phase_10.corpus_refresh._persist_proof")
@patch("phase_10.corpus_refresh.allow_paid_step", return_value=BudgetDecision(allowed=True))
def test_corpus_refresh_new_vs_existing(
    _gate,
    mock_persist,
    _existing,
    mock_spend,
    mock_collect,
    mock_pipeline,
    mock_load,
    _embed,
    _ingest,
) -> None:
    mock_persist.side_effect = lambda settings, **kw: ScrapeProof(
        job_id=kw["job_id"],
        niche=kw.get("niche"),
        summary=kw["payload"]["summary"],
        payload=kw["payload"],
        ok=True,
    )
    run = MagicMock()
    run.cost_usd = 0.5
    collection = MagicMock()
    collection.posts = [{"id": "old"}, {"id": "new"}]
    collection.enriched_posts = collection.posts
    collection.apify_runs = [run]
    collection.post_path = Path("linkedin_x.json")
    collection.profile_path = None
    mock_collect.return_value = collection
    mock_pipeline.return_value = (Path("/tmp/a.csv"), Path("/tmp/a.jsonl"))
    mock_load.return_value = [
        {"post_id": "old", "niche": "other"},
        {"post_id": "new", "niche": "other"},
    ]

    proof = run_corpus_refresh(
        "general_refresh",
        ["ai tools"],
        max_posts=10,
        settings=_settings(),
    )
    assert proof.payload["scraped"] == 2
    assert proof.payload["new"] == 1
    assert proof.payload["already"] == 1
    assert proof.payload["overlap_pct"] == 50.0
    mock_spend.assert_called_once()
    mock_pipeline.assert_called_once()
    assert mock_pipeline.call_args.kwargs.get("raw_posts") is not None


def test_tick_handlers_include_scrape_jobs() -> None:
    assert "general_refresh" in HANDLERS
    assert "niche_scrape" in HANDLERS
    assert "pro_digest" in HANDLERS
    assert "general_refresh" not in STUB_REASONS
    assert "niche_scrape" not in STUB_REASONS
    assert "pro_digest" not in STUB_REASONS


@patch("phase_10.corpus_refresh.newest_niche_posted_at")
@patch("phase_10.corpus_refresh.run_corpus_refresh")
@patch("phase_10.corpus_refresh.get_search_plan")
@patch("phase_10.corpus_refresh.active_niches", return_value=["fintech"])
@patch("phase_10.corpus_refresh._persist_proof")
def test_niche_scrape_skips_fresh(
    mock_persist,
    _active,
    mock_plan,
    mock_refresh,
    mock_newest,
) -> None:
    from phase_10.corpus_refresh import run_niche_scrape
    from phase_10.models import SearchPlan

    mock_plan.return_value = SearchPlan(
        terms=(),
        weights_by_niche={"fintech": 1.0},
        stub=False,
    )
    mock_newest.return_value = datetime.now(timezone.utc) - timedelta(hours=1)
    mock_persist.side_effect = lambda settings, **kw: ScrapeProof(
        job_id=kw["job_id"],
        summary=kw["payload"]["summary"],
        payload=kw["payload"],
        ok=True,
    )
    proof = run_niche_scrape(_settings())
    mock_refresh.assert_not_called()
    assert "skipped" in proof.summary.lower() or proof.payload.get("niches_skipped")
