"""Unit tests for processors/finalize_records.py."""

import json

import pytest

from processors.finalize_records import (
    analysed_dataset_label,
    finalize_analysed_records,
    is_analysed_dataset_filename,
    list_analysed_datasets,
    load_analysed_jsonl,
    validate_analysed_records,
)
from processors.schemas import NormalizedPost


def _stage1_record(**overrides) -> dict:
    base = {
        "post_id": "1",
        "author_public_id": "user1",
        "linkedin_url": "https://www.linkedin.com/posts/1",
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "total_engagement": 13,
        "comment_ratio": 0.2,
        "share_ratio": 0.1,
        "word_count": 50,
        "char_count": 300,
        "hashtag_count": 2,
        "emoji_count": 0,
        "has_media": False,
        "is_job_post": False,
        "hour_of_day": 10,
        "day_of_week": "Monday",
        "follower_count": None,
        "engagement_rate": None,
        "author_location_text": None,
        "author_timezone": None,
    }
    base.update(overrides)
    return base


def test_analysed_dataset_label():
    assert analysed_dataset_label(with_gemini=True) == "linkedin_analysed"
    assert analysed_dataset_label(with_gemini=False) == "linkedin_python"


def test_is_analysed_dataset_filename():
    assert is_analysed_dataset_filename("linkedin_analysed_2026-07-10_120000Z.jsonl")
    assert not is_analysed_dataset_filename("linkedin_python_2026-07-10_120000Z.jsonl")
    assert not is_analysed_dataset_filename("linkedin_2026-07-10_120000Z.jsonl")


def test_finalize_adds_benchmark_and_validates():
    records = [
        _stage1_record(post_id="1", total_engagement=10),
        _stage1_record(post_id="2", total_engagement=100),
    ]
    clean, flagged = finalize_analysed_records(records)
    assert len(clean) == 2
    assert flagged == []
    for record in clean:
        NormalizedPost.model_validate(record)
    by_id = {r["post_id"]: r for r in clean}
    assert by_id["2"]["engagement_percentile"] > by_id["1"]["engagement_percentile"]


def test_finalize_maps_author_followers_and_strips_display_fields():
    records = [
        _stage1_record(
            author_followers=1000,
            author_industry="Tech",
            author_company="Acme",
        )
    ]
    clean, _ = finalize_analysed_records(records)
    record = clean[0]
    assert record["follower_count"] == 1000
    assert record["engagement_rate"] == round(13 / 1000, 4)
    assert "author_followers" not in record
    assert "author_industry" not in record


def test_validate_analysed_records_rejects_missing_benchmark(tmp_path):
    with pytest.raises(ValueError, match="batch benchmark fields"):
        validate_analysed_records([_stage1_record()])


def test_load_analysed_jsonl_rejects_wrong_filename(tmp_path):
    path = tmp_path / "linkedin_python_2026-07-10_120000Z.jsonl"
    path.write_text(json.dumps(_stage1_record()) + "\n")
    with pytest.raises(ValueError, match="Expected a `linkedin_analysed_"):
        load_analysed_jsonl(path)


def test_list_analysed_datasets_newest_first(tmp_path):
    (tmp_path / "linkedin_analysed_2026-07-09_120000Z.jsonl").write_text("")
    (tmp_path / "linkedin_analysed_2026-07-10_120000Z.jsonl").write_text("")
    (tmp_path / "linkedin_python_2026-07-10_120000Z.jsonl").write_text("")
    names = [p.name for p in list_analysed_datasets(tmp_path)]
    assert names == [
        "linkedin_analysed_2026-07-10_120000Z.jsonl",
        "linkedin_analysed_2026-07-09_120000Z.jsonl",
    ]
