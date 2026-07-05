"""Unit tests for the NormalizedPost schema (processors/schemas.py)."""

import pytest
from pydantic import ValidationError

from processors.schemas import NormalizedPost

VALID_RECORD = {
    "post_id": "123",
    "author_public_id": "testuser",
    "linkedin_url": "https://www.linkedin.com/posts/test",
    "likes": 100,
    "comments": 20,
    "shares": 5,
    "total_engagement": 125,
    "comment_ratio": 0.2,
    "share_ratio": 0.05,
    "word_count": 42,
    "char_count": 250,
    "hashtag_count": 3,
    "emoji_count": 1,
    "has_media": True,
    "is_job_post": False,
    "hour_of_day": 14,
    "day_of_week": "Tuesday",
    "engagement_percentile": 87.5,
    "engagement_zscore": 1.23,
}


def test_accepts_a_fully_valid_record():
    post = NormalizedPost.model_validate(VALID_RECORD)
    assert post.post_id == "123"
    assert post.total_engagement == 125
    # Optional Stage 2 fields default to None when Gemini wasn't run.
    assert post.hook_type is None


def test_accepts_optional_gemini_fields_when_present():
    record = {
        **VALID_RECORD,
        "hook_type": "question",
        "tone": "professional",
        "topic": "hiring",
        "has_explicit_cta": True,
        "writing_style": "short and direct",
    }
    post = NormalizedPost.model_validate(record)
    assert post.hook_type == "question"
    assert post.has_explicit_cta is True


def test_rejects_missing_required_field():
    record = {k: v for k, v in VALID_RECORD.items() if k != "total_engagement"}
    with pytest.raises(ValidationError):
        NormalizedPost.model_validate(record)


def test_rejects_negative_engagement_counts():
    record = {**VALID_RECORD, "likes": -5}
    with pytest.raises(ValidationError):
        NormalizedPost.model_validate(record)


def test_rejects_out_of_range_percentile():
    record = {**VALID_RECORD, "engagement_percentile": 150}
    with pytest.raises(ValidationError):
        NormalizedPost.model_validate(record)


def test_rejects_invalid_hook_type_label():
    record = {**VALID_RECORD, "hook_type": "clickbait"}  # not one of the allowed labels
    with pytest.raises(ValidationError):
        NormalizedPost.model_validate(record)


def test_rejects_unknown_extra_field():
    """extra='forbid' should catch upstream fields added but never reflected here."""
    record = {**VALID_RECORD, "some_new_feature_nobody_added_to_schema": 1}
    with pytest.raises(ValidationError):
        NormalizedPost.model_validate(record)
