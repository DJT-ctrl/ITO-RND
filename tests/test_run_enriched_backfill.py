"""Unit tests for processors/run_enriched_backfill.py."""

import json

from config.settings import Settings
from processors.run_enriched_backfill import run_enriched_backfill
from storage.processed_store import ProcessedStore


def _settings(raw_dir) -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir=str(raw_dir),
        default_search_limit=10,
        database_url="",
    )


def _make_post(post_id: str, author_id: str, likes: int) -> dict:
    return {
        "id": post_id,
        "linkedinUrl": f"https://www.linkedin.com/posts/{post_id}",
        "content": f"Post {post_id} about hiring #jobs",
        "author": {
            "type": "profile",
            "publicIdentifier": author_id,
            "linkedinUrl": f"https://www.linkedin.com/in/{author_id}",
        },
        "postedAt": {"timestamp": 1783081190913},
        "postImages": [],
        "job": None,
        "engagement": {"likes": likes, "comments": 0, "shares": 0},
    }


def test_run_enriched_backfill_skip_scrape_uses_existing_profile_file(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps([_make_post("1", "user1", 10), _make_post("2", "user2", 100)])
    )
    profile_path = raw_dir / "linkedin_profiles_20260101T000000Z.json"
    profile_path.write_text(json.dumps([{"publicIdentifier": "user1", "followerCount": 1000}]))

    settings = _settings(raw_dir)
    store = ProcessedStore(base_dir=str(processed_dir))

    import processors.run_pipeline as run_pipeline_module

    original_run = run_pipeline_module.run_pipeline

    def _run_pipeline(*args, **kwargs):
        kwargs["store"] = store
        kwargs["settings"] = settings
        return original_run(*args, **kwargs)

    monkeypatch.setattr("processors.run_enriched_backfill.run_pipeline", _run_pipeline)

    csv_path, jsonl_path = run_enriched_backfill(settings=settings, skip_scrape=True)

    records = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    by_id = {r["post_id"]: r for r in records}
    assert by_id["1"]["follower_count"] == 1000
    assert by_id["1"]["audience_adjusted_percentile"] is not None
    assert csv_path.exists()
