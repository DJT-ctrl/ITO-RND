from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from processors.post_analyser import PostAnalyser


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
    analyser._model = True  # mark as initialised

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
    analyser._model = True

    result = analyser.compute_gemini_features(SAMPLE_POST, python_features)
    assert result["hook_type"] is None
    assert result["tone"] is None
