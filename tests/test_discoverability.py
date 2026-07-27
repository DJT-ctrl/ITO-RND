"""Unit tests for Tier 1 corpus-grounded discoverability (T6 Point 2)."""

from pathlib import Path

import pytest

from agents.discoverability import (
    format_discoverability_context_section,
    parse_draft_features,
    run_deterministic_checks,
    summarize_neighbors_for_seo,
)
from api.schemas import SimilarPost
from processors.corpus_benchmarks import (
    build_snapshot,
    corpus_norms_from_snapshot,
    format_snapshot_for_prompt,
    get_or_refresh_benchmarks,
    is_stale,
    load_snapshot,
    save_snapshot,
)


def _sample_records(n: int = 20) -> list[dict]:
    records = []
    for i in range(n):
        records.append(
            {
                "word_count": 200 + (i % 5) * 30,
                "char_count": 1000,
                "hashtag_count": 1 + (i % 4),
                "emoji_count": i % 3,
                "hour_of_day": 9,
                "has_media": i % 2 == 0,
                "is_job_post": False,
                "has_explicit_cta": i % 3 == 0,
                "hook_type": "story",
                "tone": "professional",
                "topic": "hiring" if i % 2 == 0 else "AI tooling",
                "day_of_week": "Tuesday",
                "engagement_percentile": 10.0 + i * 4,
                "engagement_zscore": -1.0 + i * 0.1,
                "audience_adjusted_percentile": None,
                "audience_adjusted_zscore": None,
            }
        )
    return records


def test_parse_draft_features_counts_hashtags_and_words():
    draft = "#hiring Excited to share our backend opening today."
    features = parse_draft_features(draft)

    assert features["hashtag_count"] == 1
    assert features["word_count"] == 8
    assert features["starts_with_hashtag"] is True


def test_run_deterministic_checks_flags_hashtag_opening_line():
    draft = "#hiring We are growing the team " + "word " * 40
    norms = {"optimal_hashtag_range": (1, 3), "optimal_word_count_range": (150, 350)}
    result = run_deterministic_checks(draft, norms)

    opening = next(s for s in result["signals"] if s["check"] == "opening_line")
    assert opening["status"] == "fail"
    assert 0 <= result["deterministic_score"] <= 10


def test_run_deterministic_checks_passes_clean_opening_and_hashtags():
    draft = "Hiring backend engineers for our platform. " + "word " * 35 + "#hiring #backend"
    norms = {"optimal_hashtag_range": (1, 3), "optimal_word_count_range": (150, 350)}
    result = run_deterministic_checks(draft, norms)

    opening = next(s for s in result["signals"] if s["check"] == "opening_line")
    hashtags = next(s for s in result["signals"] if s["check"] == "hashtag_count")
    assert opening["status"] == "pass"
    assert hashtags["status"] == "pass"


def test_summarize_neighbors_for_seo_is_compact():
    posts = [
        SimilarPost(
            post_id="1",
            content="Hiring update for backend roles #hiring",
            likes=10,
            comments=2,
            shares=1,
            total_engagement=13,
            engagement_percentile=80.0,
            engagement_zscore=1.2,
            cosine_distance=0.1,
            hashtag_count=1,
            word_count=6,
            topic="hiring",
            hook_type="announcement",
        )
    ]
    summary = summarize_neighbors_for_seo(posts)

    assert "Neighbor 1" in summary
    assert "hiring" in summary.lower()
    assert "Engagement percentile: 80.0" in summary


def test_summarize_neighbors_handles_empty_list():
    assert "No comparable" in summarize_neighbors_for_seo([])


def test_build_snapshot_produces_compact_summary():
    snapshot = build_snapshot(_sample_records())

    assert snapshot["sample_size"] == 20
    assert "optimal_hashtag_range" in snapshot
    assert "optimal_word_count_range" in snapshot
    assert isinstance(snapshot.get("top_topics"), list)


def test_snapshot_cache_round_trip(tmp_path: Path):
    path = tmp_path / "corpus_benchmarks.json"
    snapshot = build_snapshot(_sample_records())
    save_snapshot(snapshot, path)

    loaded = load_snapshot(path)
    assert loaded is not None
    assert loaded["sample_size"] == 20
    assert is_stale(path, ttl_hours=24) is False


def test_format_snapshot_for_prompt_includes_corpus_size():
    snapshot = build_snapshot(_sample_records())
    text = format_snapshot_for_prompt(snapshot)

    assert "Corpus size: 20" in text
    assert "hashtag" in text.lower()


def test_corpus_norms_from_snapshot():
    snapshot = build_snapshot(_sample_records())
    norms = corpus_norms_from_snapshot(snapshot)

    assert "optimal_hashtag_range" in norms
    assert "optimal_word_count_range" in norms


def test_get_or_refresh_benchmarks_without_db_uses_cache(tmp_path, monkeypatch):
    path = tmp_path / "corpus_benchmarks.json"
    save_snapshot(build_snapshot(_sample_records()), path)

    from config.settings import Settings

    settings = Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="",
    )
    monkeypatch.setattr("processors.corpus_benchmarks.DEFAULT_SNAPSHOT_PATH", path)

    snapshot, warnings = get_or_refresh_benchmarks(settings, path=path)
    assert snapshot is not None
    assert snapshot["sample_size"] == 20
    assert not warnings


def test_get_or_refresh_benchmarks_without_db_or_cache_returns_none():
    from config.settings import Settings

    settings = Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="",
    )
    snapshot, warnings = get_or_refresh_benchmarks(settings, path=Path("nonexistent/benchmarks.json"))
    assert snapshot is None
    assert warnings


def _settings_with_database_url():
    from config.settings import Settings

    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://unreachable.invalid:5432/ito",
    )


def test_get_or_refresh_benchmarks_db_unavailable_uses_stale_cache(tmp_path, monkeypatch):
    """DB/network failure during refresh must fall back to cached snapshot."""
    import psycopg

    path = tmp_path / "corpus_benchmarks.json"
    save_snapshot(build_snapshot(_sample_records()), path)
    settings = _settings_with_database_url()

    def _raise_operational_error(*_args, **_kwargs):
        raise psycopg.OperationalError("failed to resolve host")

    monkeypatch.setattr(
        "processors.corpus_benchmarks.refresh_snapshot_from_db",
        _raise_operational_error,
    )

    snapshot, warnings = get_or_refresh_benchmarks(settings, force=True, path=path)

    assert snapshot is not None
    assert snapshot["sample_size"] == 20
    assert any("failed to resolve host" in w for w in warnings)
    assert any("stale corpus benchmark cache" in w for w in warnings)


def test_get_or_refresh_benchmarks_db_unavailable_no_cache_returns_none(tmp_path, monkeypatch):
    """DB/network failure with no cache must return None + warning, not raise."""
    import psycopg

    path = tmp_path / "missing_benchmarks.json"
    settings = _settings_with_database_url()

    def _raise_operational_error(*_args, **_kwargs):
        raise psycopg.OperationalError("failed to resolve host")

    monkeypatch.setattr(
        "processors.corpus_benchmarks.refresh_snapshot_from_db",
        _raise_operational_error,
    )

    snapshot, warnings = get_or_refresh_benchmarks(settings, force=True, path=path)

    assert snapshot is None
    assert any("failed to resolve host" in w for w in warnings)


def test_format_discoverability_context_section_includes_evidence():
    section = format_discoverability_context_section(
        {
            "corpus_benchmark_text": "- Corpus size: 10 posts",
            "deterministic": {
                "deterministic_score": 8.0,
                "signals": [{"check": "hashtag_count", "status": "pass", "note": "ok"}],
            },
            "neighbor_summary": "Neighbor 1: percentile 80",
        }
    )

    assert "Corpus benchmark snapshot" in section
    assert "Deterministic draft checks" in section
    assert "Nearest historical posts" in section


def test_format_discoverability_context_section_includes_trends():
    section = format_discoverability_context_section(
        {
            "trends_text": (
                "External trend signal (Google Trends — web-wide, NOT LinkedIn-specific):\n"
                "- Disclaimer: web-wide only"
            ),
        }
    )

    assert "NOT LinkedIn-specific" in section


def test_build_snapshot_requires_records():
    with pytest.raises(ValueError, match="empty"):
        build_snapshot([])
