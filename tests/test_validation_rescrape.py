"""Tests for validation_pipeline.rescrape URL matching."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from validation_pipeline.rescrape import (
    _normalize_post_url,
    extract_engagement,
    fetch_engagement_by_urls,
    match_post_in_results,
)
from validation_pipeline.schemas import PredictionRecord
from scrapers.result import ScrapeResult


def _prediction(**kwargs) -> PredictionRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        prediction_id=uuid4(),
        linkedin_post_id="7330988768578920448",
        linkedin_url="https://www.linkedin.com/posts/user_activity-7330988768578920448-abc",
        author_public_id="user",
        content="We are hiring engineers for our platform team.",
        posted_at=now,
        predicted_engagement_percentile=55.0,
        validation_due_at=now,
    )
    defaults.update(kwargs)
    return PredictionRecord(**defaults)


def test_normalize_post_url_strips_query():
    raw = "https://www.linkedin.com/posts/foo-activity-123?utm_source=share"
    assert _normalize_post_url(raw) == "https://www.linkedin.com/posts/foo-activity-123"


def test_match_post_by_id():
    prediction = _prediction()
    items = [
        {"id": "other", "linkedinUrl": "https://example.com/1"},
        {"id": prediction.linkedin_post_id, "linkedinUrl": prediction.linkedin_url},
    ]
    matched = match_post_in_results(items, prediction)
    assert matched is not None
    assert matched["id"] == prediction.linkedin_post_id


def test_match_post_by_url_when_id_differs():
    prediction = _prediction()
    items = [{"id": "different", "linkedinUrl": prediction.linkedin_url}]
    matched = match_post_in_results(items, prediction)
    assert matched is not None


def test_match_post_by_entity_id():
    prediction = _prediction()
    items = [{"entityId": prediction.linkedin_post_id, "linkedinUrl": "https://example.com/x"}]
    matched = match_post_in_results(items, prediction)
    assert matched is not None


def test_extract_engagement():
    post = {"engagement": {"likes": 3, "comments": 2, "shares": 1}}
    actuals = extract_engagement(post)
    assert actuals.total_engagement == 6


def test_fetch_engagement_falls_back_to_author_profile():
    prediction = _prediction(
        linkedin_post_id="7480224350739034112",
        linkedin_url="https://www.linkedin.com/posts/user_activity-7480224350739034112-abc",
        author_public_id="user",
    )
    settings = MagicMock()
    settings.validation_rescrape_profile_max_posts = 50
    settings.validation_data_dir = "data/validation"

    scraper = MagicMock()
    scraper.fetch_posts_by_urls.side_effect = [
        ScrapeResult(items=[], run_record=None),
        ScrapeResult(items=[], run_record=None),
        ScrapeResult(
            items=[
                {
                    "id": prediction.linkedin_post_id,
                    "linkedinUrl": prediction.linkedin_url,
                    "engagement": {"likes": 4, "comments": 1, "shares": 0},
                }
            ],
            run_record=None,
        ),
    ]

    actuals = fetch_engagement_by_urls(
        [prediction],
        settings,
        scraper=scraper,
        context="test",
    )

    assert actuals[prediction.prediction_id].total_engagement == 5
    profile_call = scraper.fetch_posts_by_urls.call_args_list[-1]
    assert profile_call.args[0] == ["https://www.linkedin.com/in/user"]
    assert profile_call.kwargs["max_posts"] == 50
