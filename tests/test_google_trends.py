"""Unit tests for Tier 2 Google Trends discoverability."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from agents.discoverability_context import gather_discoverability_context, resolve_use_google_trends
from config.settings import Settings
from processors.trend_signals.google_trends import (
    _corpus_alignment,
    _is_cache_stale,
    classify_direction,
    fetch_trend_signals,
    format_trends_for_prompt,
)
from processors.trend_signals.keywords import extract_trend_keywords


def make_settings(**overrides) -> Settings:
    defaults = {
        "apify_api_token": "",
        "apify_actor_id": "",
        "apify_profile_actor_id": "",
        "linkedin_cookies": [],
        "gemini_api_key": "",
        "raw_data_dir": "data/raw",
        "default_search_limit": 20,
        "database_url": "",
        "google_trends_enabled": True,
        "google_trends_cache_ttl_hours": 12,
        "google_trends_geo": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_extract_trend_keywords_from_hashtags_and_sentence():
    draft = "Excited to announce our backend hiring push #hiring #backend"
    keywords = extract_trend_keywords(
        draft,
        corpus_top_topics=[{"topic": "hiring"}],
    )

    assert any("hiring" in k.lower() for k in keywords)
    assert "excited" not in [k.lower() for k in keywords]
    assert len(keywords) <= 3


def test_extract_trend_keywords_prefers_corpus_overlap():
    draft = "Our team is growing across platform engineering and hiring."
    keywords = extract_trend_keywords(
        draft,
        corpus_top_topics=[{"topic": "hiring"}, {"topic": "AI tooling"}],
    )

    assert keywords
    assert keywords[0].lower() == "hiring" or "hiring" in keywords[0].lower()


def test_classify_direction_rising():
    index = pd.date_range("2025-01-01", periods=90, freq="D")
    values = [20] * 60 + [80] * 30
    direction, recent, prior = classify_direction(pd.Series(values, index=index))

    assert direction == "rising"
    assert recent is not None and prior is not None
    assert recent > prior


def test_classify_direction_insufficient_data():
    direction, recent, prior = classify_direction(pd.Series([10, 12], index=[0, 1]))
    assert direction == "insufficient_data"
    assert recent is None and prior is None


def test_corpus_alignment_web_trend_only_for_rising_non_corpus_keyword():
    alignment = _corpus_alignment(
        "celebrity news",
        "rising",
        [{"topic": "hiring"}],
    )
    assert alignment == "web_trend_only"


def test_corpus_alignment_aligned_for_rising_corpus_keyword():
    alignment = _corpus_alignment(
        "hiring",
        "rising",
        [{"topic": "hiring"}],
    )
    assert alignment == "aligned"


def test_corpus_alignment_stale_for_falling_keyword():
    alignment = _corpus_alignment("hiring", "falling", [{"topic": "hiring"}])
    assert alignment == "stale"


def test_format_trends_for_prompt_includes_disclaimer():
    text = format_trends_for_prompt(
        {
            "disclaimer": "Google Trends reflects web-wide search interest, not LinkedIn feed performance.",
            "signals": [
                {
                    "keyword": "hiring",
                    "direction": "rising",
                    "recent_avg": 68.0,
                    "prior_avg": 41.0,
                    "corpus_alignment": "aligned",
                }
            ],
        }
    )

    assert text is not None
    assert "NOT LinkedIn-specific" in text
    assert "hiring" in text
    assert "aligned" in text


def test_fetch_trend_signals_uses_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "trend_cache.json"
    monkeypatch.setattr("processors.trend_signals.google_trends.DEFAULT_CACHE_PATH", cache_path)

    cached_signal = {
        "keyword": "hiring",
        "direction": "rising",
        "recent_avg": 50.0,
        "prior_avg": 30.0,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "geo": "",
        "timeframe": "today 3-m",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        '{"hiring|GLOBAL|today 3-m": ' + json.dumps(cached_signal) + "}",
        encoding="utf-8",
    )

    trends, warnings = fetch_trend_signals(["hiring"], make_settings(), corpus_top_topics=[{"topic": "hiring"}])

    assert trends is not None
    assert trends["signals"][0]["keyword"] == "hiring"
    assert warnings == []


@patch("processors.trend_signals.google_trends._fetch_keyword_signal")
def test_fetch_trend_signals_degrades_on_fetch_error(mock_fetch):
    mock_fetch.side_effect = RuntimeError("rate limited")

    trends, warnings = fetch_trend_signals(["hiring"], make_settings())

    assert trends is None
    assert any("rate limited" in warning for warning in warnings)


def test_is_cache_stale_respects_ttl():
    fresh = {"fetched_at": datetime.now(timezone.utc).isoformat()}
    stale = {"fetched_at": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}

    assert _is_cache_stale(fresh, ttl_hours=12) is False
    assert _is_cache_stale(stale, ttl_hours=12) is True


def test_resolve_use_google_trends_off_by_default():
    settings = make_settings(google_trends_enabled=False)
    assert resolve_use_google_trends("corpus", settings) is False


def test_resolve_use_google_trends_off_in_gemini_only_mode():
    settings = make_settings(google_trends_enabled=True)
    assert resolve_use_google_trends("gemini_only", settings) is False
    assert resolve_use_google_trends("gemini_only", settings, use_google_trends=True) is False


def test_resolve_use_google_trends_honors_request_override():
    settings = make_settings(google_trends_enabled=True)
    assert resolve_use_google_trends("corpus", settings, use_google_trends=False) is False
    assert resolve_use_google_trends("corpus", settings, use_google_trends=True) is True


@patch("agents.discoverability_context.fetch_trend_signals")
@patch("agents.discoverability_context.get_or_refresh_benchmarks")
def test_gather_discoverability_context_skips_trends_when_disabled(mock_benchmarks, mock_trends):
    mock_benchmarks.return_value = (
        {
            "sample_size": 10,
            "top_topics": [{"topic": "hiring", "mean_zscore": 1.0, "count": 5}],
            "optimal_hashtag_range": [1, 3],
            "optimal_word_count_range": [150, 350],
        },
        [],
    )

    context, warnings = gather_discoverability_context(
        "Hiring backend engineers today #hiring",
        [],
        make_settings(),
        use_google_trends=False,
    )

    mock_trends.assert_not_called()
    assert "trends" not in context
    assert warnings == []


@patch("agents.discoverability_context.fetch_trend_signals")
@patch("agents.discoverability_context.get_or_refresh_benchmarks")
def test_gather_discoverability_context_includes_trends_when_enabled(mock_benchmarks, mock_trends):
    mock_benchmarks.return_value = (
        {
            "sample_size": 10,
            "top_topics": [{"topic": "hiring", "mean_zscore": 1.0, "count": 5}],
            "optimal_hashtag_range": [1, 3],
            "optimal_word_count_range": [150, 350],
        },
        [],
    )
    mock_trends.return_value = (
        {
            "disclaimer": "Google Trends reflects web-wide search interest, not LinkedIn feed performance.",
            "keywords": ["hiring"],
            "signals": [{"keyword": "hiring", "direction": "rising", "corpus_alignment": "aligned"}],
        },
        [],
    )

    context, _ = gather_discoverability_context(
        "Hiring backend engineers today #hiring",
        [],
        make_settings(),
        use_google_trends=True,
    )

    mock_trends.assert_called_once()
    assert "trends" in context
    assert "trends_text" in context
    assert "NOT LinkedIn-specific" in context["trends_text"]
