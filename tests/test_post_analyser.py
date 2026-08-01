from unittest.mock import MagicMock, patch

import json
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
    analyser._model = "gemini-2.5-flash-lite"

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
    analyser._model = "gemini-2.5-flash-lite"

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
    analyser._model = "gemini-2.5-flash-lite"

    result = analyser.compute_gemini_features(SAMPLE_POST, python_features)
    assert result["hook_type"] is None
    assert "model not found" in (analyser.last_error or "")


def test_gemini_features_retries_transient_503_then_succeeds():
    from google.genai import errors as genai_errors

    good_response = MagicMock()
    good_response.text = json.dumps(
        {
            "hook_type": "announcement",
            "tone": "professional",
            "topic": "AI tools",
            "has_explicit_cta": False,
            "writing_style": "Short update.",
        }
    )

    analyser = PostAnalyser(make_settings())
    python_features = analyser.compute_python_features(SAMPLE_POST)
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        genai_errors.APIError(503, {"error": {"message": "high demand"}}),
        good_response,
    ]
    analyser._client = mock_client
    analyser._model = "gemini-2.5-flash-lite"

    with patch("processors.gemini_retry.time.sleep") as mock_sleep:
        result = analyser.compute_gemini_features(SAMPLE_POST, python_features)

    assert result["hook_type"] == "announcement"
    mock_sleep.assert_called_once()


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


# ── Stage 2 batch (map_gemini_features) ───────────────────────────────────────

def _sample_post(post_id: str, content: str = "Hello world #ai") -> dict:
    return {
        **SAMPLE_POST,
        "id": post_id,
        "content": content,
    }


def _ok_features(topic: str) -> dict:
    return {
        "hook_type": "announcement",
        "tone": "professional",
        "topic": topic,
        "has_explicit_cta": False,
        "writing_style": "Short update.",
        "niche": None,
    }


def test_map_gemini_features_preserves_order_with_workers():
    import time

    from processors.post_analyser import map_gemini_features

    posts = [_sample_post(f"p{i}") for i in range(5)]
    settings = make_settings()
    analyser = PostAnalyser(settings)
    python_records = [analyser.compute_python_features(p) for p in posts]

    delays = {0: 0.05, 1: 0.01, 2: 0.04, 3: 0.02, 4: 0.03}

    def fake_compute(self, post, python_features):
        time.sleep(delays[int(str(post["id"]).lstrip("p"))])
        self.last_error = None
        return _ok_features(topic=f"topic-{post['id']}")

    progress_calls: list[tuple[int, int]] = []

    with patch.object(PostAnalyser, "compute_gemini_features", fake_compute):
        results = map_gemini_features(
            posts,
            python_records,
            settings,
            max_workers=4,
            on_progress=lambda done, total: progress_calls.append((done, total)),
        )

    assert [r["topic"] for r in results] == [f"topic-p{i}" for i in range(5)]
    assert len(results) == len(posts)
    assert progress_calls[-1] == (5, 5)
    assert sorted(done for done, _ in progress_calls) == [1, 2, 3, 4, 5]


def test_map_gemini_features_partial_failure_keeps_others():
    from processors.post_analyser import map_gemini_features

    posts = [_sample_post("ok1"), _sample_post("bad"), _sample_post("ok2")]
    settings = make_settings()
    analyser = PostAnalyser(settings)
    python_records = [analyser.compute_python_features(p) for p in posts]
    errors: list[str] = []

    def fake_compute(self, post, python_features):
        if post["id"] == "bad":
            self.last_error = "Post bad: boom"
            return PostAnalyser._empty_gemini_features()
        self.last_error = None
        return _ok_features(topic=f"topic-{post['id']}")

    with patch.object(PostAnalyser, "compute_gemini_features", fake_compute):
        results = map_gemini_features(
            posts,
            python_records,
            settings,
            max_workers=3,
            on_error=errors.append,
        )

    assert results[0]["topic"] == "topic-ok1"
    assert results[1]["hook_type"] is None
    assert results[2]["topic"] == "topic-ok2"
    assert errors == ["Post bad: boom"]


def test_map_gemini_features_workers_one_is_sequential():
    from processors.post_analyser import map_gemini_features

    posts = [_sample_post(f"p{i}") for i in range(3)]
    settings = make_settings()
    analyser = PostAnalyser(settings)
    python_records = [analyser.compute_python_features(p) for p in posts]
    call_order: list[str] = []

    def fake_compute(self, post, python_features):
        call_order.append(post["id"])
        self.last_error = None
        return _ok_features(topic=f"topic-{post['id']}")

    with patch.object(PostAnalyser, "compute_gemini_features", fake_compute):
        results = map_gemini_features(
            posts,
            python_records,
            settings,
            max_workers=1,
        )

    assert call_order == ["p0", "p1", "p2"]
    assert [r["topic"] for r in results] == ["topic-p0", "topic-p1", "topic-p2"]


def test_map_gemini_features_rejects_length_mismatch():
    from processors.post_analyser import map_gemini_features

    with pytest.raises(ValueError, match="length mismatch"):
        map_gemini_features([_sample_post("a")], [], make_settings(), max_workers=1)
