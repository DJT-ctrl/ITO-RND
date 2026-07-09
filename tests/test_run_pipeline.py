"""Unit tests for the batch pipeline entry point (processors/run_pipeline.py).

Only exercises Stage 1 + benchmark (with_gemini=False) — Stage 2 requires a
real Gemini API call, which processors/post_analyser.py already has its own
mocked tests for. Settings/store are injected so nothing here touches the
real data/raw or data/processed directories.
"""

import json

import pytest

from config.settings import Settings
from processors.run_pipeline import load_raw_posts, run_pipeline
from processors.schemas import NormalizedPost
from storage.processed_store import ProcessedStore

def make_settings(raw_data_dir: str) -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir=raw_data_dir,
        default_search_limit=10,
    )


def make_post(
    post_id: str,
    likes: int,
    comments: int = 0,
    shares: int = 0,
    content: str = "A test post about hiring #jobs",
) -> dict:
    return {
        "id": post_id,
        "linkedinUrl": f"https://www.linkedin.com/posts/{post_id}",
        "content": content,
        "author": {"publicIdentifier": f"user{post_id}"},
        "postedAt": {"timestamp": 1783081190913},
        "postImages": [],
        "job": None,
        "engagement": {"likes": likes, "comments": comments, "shares": shares},
    }


# ── load_raw_posts ──────────────────────────────────────────────────────────────

def test_load_raw_posts_concatenates_all_post_scans(tmp_path):
    (tmp_path / "linkedin_20260101T000000Z.json").write_text(
        json.dumps([make_post("1", 10), make_post("2", 20)])
    )
    (tmp_path / "linkedin_20260102T000000Z.json").write_text(json.dumps([make_post("3", 30)]))

    posts = load_raw_posts(str(tmp_path))
    assert {p["id"] for p in posts} == {"1", "2", "3"}


def test_load_raw_posts_excludes_profile_scans(tmp_path):
    (tmp_path / "linkedin_20260101T000000Z.json").write_text(json.dumps([make_post("1", 10)]))
    (tmp_path / "linkedin_profiles_20260101T000000Z.json").write_text(
        json.dumps([{"publicIdentifier": "someone", "followersCount": 500}])
    )

    posts = load_raw_posts(str(tmp_path))
    assert len(posts) == 1
    assert posts[0]["id"] == "1"


# ── run_pipeline (Stage 1 + benchmark only) ─────────────────────────────────────

def test_run_pipeline_writes_csv_and_jsonl_with_valid_records(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps(
            [
                make_post("1", 10, 2, 1, content="A test post about hiring #jobs"),
                make_post("2", 100, 20, 5, content="A different test post about engineering #tech"),
            ]
        )
    )

    settings = make_settings(str(raw_dir))
    store = ProcessedStore(base_dir=str(processed_dir))

    csv_path, jsonl_path = run_pipeline(with_gemini=False, settings=settings, store=store)

    assert csv_path.exists()
    assert jsonl_path.exists()

    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]

    # Every persisted record must be a valid NormalizedPost — this is the
    # whole point of validating before save() in run_pipeline.
    for record in records:
        NormalizedPost.model_validate(record)

    # The post with more engagement should rank higher in the benchmark.
    by_id = {r["post_id"]: r for r in records}
    assert by_id["2"]["engagement_percentile"] > by_id["1"]["engagement_percentile"]


def test_run_pipeline_raises_when_no_raw_posts_found(tmp_path):
    settings = make_settings(str(tmp_path))  # empty dir, no scan files
    store = ProcessedStore(base_dir=str(tmp_path / "processed"))
    with pytest.raises(ValueError):
        run_pipeline(with_gemini=False, settings=settings, store=store)


def test_run_pipeline_default_path_never_populates_audience_adjusted_fields(tmp_path):
    """with_profile_enrichment defaults to False: the optional fields must
    all be None, confirming the old path is completely unaffected."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps([make_post("1", 10, 2, 1, content="A test post about hiring #jobs")])
    )

    settings = make_settings(str(raw_dir))
    store = ProcessedStore(base_dir=str(tmp_path / "processed"))
    _, jsonl_path = run_pipeline(settings=settings, store=store)

    record = json.loads(jsonl_path.read_text().splitlines()[0])
    assert record["follower_count"] is None
    assert record["audience_adjusted_percentile"] is None
    assert record["audience_adjusted_zscore"] is None
    assert record["engagement_rate"] is None


# ── run_pipeline (with_profile_enrichment=True, T6 Point 1) ─────────────────

def test_run_pipeline_profile_enrichment_raises_clearly_without_a_profile_file(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(json.dumps([make_post("1", 10)]))

    settings = make_settings(str(raw_dir))
    store = ProcessedStore(base_dir=str(tmp_path / "processed"))

    with pytest.raises(ValueError, match="no profile scrape"):
        run_pipeline(with_profile_enrichment=True, settings=settings, store=store)


def test_run_pipeline_profile_enrichment_allows_partial_author_coverage(tmp_path):
    """Only user1 has a matching profile record; user2 doesn't. The batch
    must still succeed, with user1 getting follower-normalized fields and
    user2 simply falling back to None (not an error)."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "linkedin_20260101T000000Z.json").write_text(
        json.dumps(
            [
                make_post("1", 10, 2, 1, content="A test post about hiring #jobs"),
                make_post("2", 100, 20, 5, content="A different test post about engineering #tech"),
            ]
        )
    )
    (raw_dir / "linkedin_profiles_20260101T000000Z.json").write_text(
        json.dumps([{"publicIdentifier": "user1", "followerCount": 1000}])
    )

    settings = make_settings(str(raw_dir))
    store = ProcessedStore(base_dir=str(tmp_path / "processed"))

    _, jsonl_path = run_pipeline(with_profile_enrichment=True, settings=settings, store=store)
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    by_id = {r["post_id"]: r for r in records}

    assert by_id["1"]["follower_count"] == 1000
    assert by_id["1"]["engagement_rate"] is not None
    assert by_id["1"]["audience_adjusted_percentile"] is not None

    assert by_id["2"]["follower_count"] is None
    assert by_id["2"]["audience_adjusted_percentile"] is None

    for record in records:
        NormalizedPost.model_validate(record)
