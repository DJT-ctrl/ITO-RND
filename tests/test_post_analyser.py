from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from processors.post_analyser import PostAnalyser, _build_gemini_prompt


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-gemini-key",
        raw_data_dir="data/raw",
        default_search_limit=10,
    )
    defaults.update(overrides)
    return Settings(**defaults)


SAMPLE_POST = {
    "id": "123",
    "linkedinUrl": "https://www.linkedin.com/posts/test",
    "content": "Excited to announce 🎉 we are #hiring! Drop a comment below if interested. #jobs #tech",
    "author": {"publicIdentifier": "testuser", "linkedinUrl": "https://www.linkedin.com/in/testuser"},
    "postedAt": {"timestamp": 1783081190913},
    "postImages": [{"url": "https://example.com/img.jpg"}],
    "job": None,
    "engagement": {"likes": 100, "comments": 20, "shares": 5},
}


# ── Stage 1 (Python features) ─────────────────────────────────────────────────

def test_python_features_engagement():
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["likes"] == 100
    assert features["comments"] == 20
    assert features["shares"] == 5
    assert features["total_engagement"] == 125


def test_python_features_ratios():
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["comment_ratio"] == round(20 / 100, 3)
    assert features["share_ratio"] == round(5 / 100, 3)


def test_python_features_zero_likes_gives_none_ratios():
    post = {**SAMPLE_POST, "engagement": {"likes": 0, "comments": 3, "shares": 1}}
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(post)
    assert features["comment_ratio"] is None
    assert features["share_ratio"] is None


def test_python_features_text_metrics():
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["hashtag_count"] == 3  # #hiring, #jobs, #tech
    assert features["emoji_count"] == 1    # 🎉
    assert features["has_media"] is True
    assert features["is_job_post"] is False


def test_python_features_timing():
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["hour_of_day"] is not None
    assert features["day_of_week"] in (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    )


def test_python_features_join_keys():
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["post_id"] == "123"
    assert features["author_public_id"] == "testuser"


# ── Stage 1: optional profile-enrichment fields (T6 Point 1) ─────────────────

def test_python_features_enrichment_fields_are_none_by_default():
    """A post that never went through --with-profile-enrichment must get
    None for every follower/location field — this is the "old path
    unchanged" guarantee."""
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(SAMPLE_POST)
    assert features["follower_count"] is None
    assert features["author_location_text"] is None
    assert features["author_timezone"] is None
    assert features["engagement_rate"] is None


def test_python_features_computes_engagement_rate_when_follower_count_present():
    post = {**SAMPLE_POST, "follower_count": 500}
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(post)
    # total_engagement = 125, follower_count = 500
    assert features["engagement_rate"] == round(125 / 500, 4)
    assert features["follower_count"] == 500


def test_python_features_engagement_rate_none_when_follower_count_zero():
    post = {**SAMPLE_POST, "follower_count": 0}
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(post)
    assert features["engagement_rate"] is None


def test_python_features_uses_local_time_when_location_resolves():
    post = {**SAMPLE_POST, "location_text": "Long Beach, California, United States"}
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(post)
    assert features["author_timezone"] == "America/Los_Angeles"
    assert features["author_location_text"] == "Long Beach, California, United States"
    # 2026-07-03T12:19:50.913Z -> 05:19 America/Los_Angeles (PDT, UTC-7)
    assert features["hour_of_day"] == 5
    assert features["day_of_week"] == "Friday"


def test_python_features_falls_back_to_utc_when_location_unresolvable():
    post = {**SAMPLE_POST, "location_text": "Somewhere, Nowhereland"}
    analyser = PostAnalyser(make_settings())
    features = analyser.compute_python_features(post)
    assert features["author_timezone"] is None
    assert features["hour_of_day"] == 12  # UTC, same as the non-enriched path


# ── Stage 2 (Gemini features) ─────────────────────────────────────────────────

def test_gemini_features_raises_without_key():
    analyser = PostAnalyser(make_settings(gemini_api_key=""))
    python_features = analyser.compute_python_features(SAMPLE_POST)
    with pytest.raises(ValueError):
        analyser.compute_gemini_features(SAMPLE_POST, python_features)


def test_gemini_features_returns_parsed_json():
    fake_response = MagicMock()
    fake_response.text = '{"hook_type": "announcement", "tone": "professional", "topic": "job hiring", "has_explicit_cta": true, "writing_style": "short announcement"}'

    analyser = PostAnalyser(make_settings())
    python_features = analyser.compute_python_features(SAMPLE_POST)

    # Inject a mock client directly so no real HTTP call is made
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response
    analyser._client = mock_client
    analyser._model = "gemini-2.5-flash"

    result = analyser.compute_gemini_features(SAMPLE_POST, python_features)

    assert result["hook_type"] == "announcement"
    assert result["has_explicit_cta"] is True


def test_gemini_features_returns_nulls_on_bad_response():
    bad_response = MagicMock()
    bad_response.text = "not valid json {{{"

    analyser = PostAnalyser(make_settings())
    python_features = analyser.compute_python_features(SAMPLE_POST)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = bad_response
    analyser._client = mock_client
    analyser._model = "gemini-2.5-flash"

    result = analyser.compute_gemini_features(SAMPLE_POST, python_features)
    assert result["hook_type"] is None
    assert result["tone"] is None


def test_gemini_features_logs_api_error_and_returns_nulls():
    from google.genai import errors as genai_errors

    analyser = PostAnalyser(make_settings())
    python_features = analyser.compute_python_features(SAMPLE_POST)
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = genai_errors.ClientError(
        404,
        {"error": {"message": "model not found"}},
        None,
    )
    analyser._client = mock_client
    analyser._model = "gemini-2.5-flash"

    result = analyser.compute_gemini_features(SAMPLE_POST, python_features)
    assert result["hook_type"] is None
    assert "model not found" in (analyser.last_error or "")


def test_build_gemini_prompt_handles_curly_braces_in_content():
    prompt = _build_gemini_prompt(
        content="Use {mustache} and {{escaped}} in your posts",
        word_count=5,
        hashtag_count=1,
        has_media=False,
    )
    assert "Use {mustache} and {{escaped}} in your posts" in prompt
    assert "<post_content>" in prompt
    assert "__CONTENT__" not in prompt


def test_verify_gemini_api_reports_missing_key():
    from processors.post_analyser import verify_gemini_api

    ok, message = verify_gemini_api(make_settings(gemini_api_key=""))
    assert ok is False
    assert "GEMINI_API_KEY" in message
