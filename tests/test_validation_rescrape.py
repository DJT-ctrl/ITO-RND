"""Tests for validation_pipeline.rescrape URL matching."""

from datetime import datetime, timezone
from uuid import uuid4

from validation_pipeline.rescrape import (
    _normalize_post_url,
    extract_engagement,
    match_post_in_results,
)
from validation_pipeline.schemas import PredictionRecord


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


def test_extract_engagement():
    post = {"engagement": {"likes": 3, "comments": 2, "shares": 1}}
    actuals = extract_engagement(post)
    assert actuals.total_engagement == 6
